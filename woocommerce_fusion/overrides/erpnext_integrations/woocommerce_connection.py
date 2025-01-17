import json
import random
from urllib.parse import urlparse

import frappe
from erpnext.erpnext_integrations.connectors.woocommerce_connection import (
	add_tax_details,
	create_address,
	create_contact,
	rename_address,
	verify_request,
)
from frappe import _
from frappe.utils.data import cstr

from woocommerce_fusion.woocommerce.doctype.woocommerce_order.woocommerce_order import (
	WC_ORDER_STATUS_MAPPING_REVERSE,
)


@frappe.whitelist(allow_guest=True)
def custom_order(*args, **kwargs):
	"""
	Overrided version of erpnext.erpnext_integrations.connectors.woocommerce_connection.order
	in order to populate our custom fields when a Webhook is received
	"""
	try:
		# ==================================== Custom code starts here ==================================== #
		# Original code
		# _order(*args, **kwargs)
		_custom_order(*args, **kwargs)
		# ==================================== Custom code starts here ==================================== #
	except Exception:
		error_message = (
			# ==================================== Custom code starts here ==================================== #
			# Original Code
			# frappe.get_traceback() + "\n\n Request Data: \n" + json.loads(frappe.request.data).__str__()
			frappe.get_traceback()
			+ "\n\n Request Data: \n"
			+ str(frappe.request.data)
			# ==================================== Custom code starts here ==================================== #
		)
		frappe.log_error("WooCommerce Error", error_message)
		raise


def _custom_order(*args, **kwargs):
	"""
	Overrided version of erpnext.erpnext_integrations.connectors.woocommerce_connection._order
	in order to populate our custom fields when a Webhook is received
	"""
	woocommerce_settings = frappe.get_doc("Woocommerce Settings")
	if frappe.flags.woocomm_test_order_data:
		order = frappe.flags.woocomm_test_order_data
		event = "created"

	elif frappe.request and frappe.request.data:
		verify_request()
		try:
			order = json.loads(frappe.request.data)
		except ValueError:
			# woocommerce returns 'webhook_id=value' for the first request which is not JSON
			order = frappe.request.data
		event = frappe.get_request_header("X-Wc-Webhook-Event")

	else:
		return "success"

	if event == "created":
		sys_lang = frappe.get_single("System Settings").language or "en"
		raw_billing_data = order.get("billing")
		raw_shipping_data = order.get("shipping")
		customer_name = f"{raw_billing_data.get('first_name')} {raw_billing_data.get('last_name')}"
		customer_docname = link_customer_and_address(raw_billing_data, raw_shipping_data, customer_name)
		# ==================================== Custom code starts here ==================================== #
		# Original code
		# link_items(order.get("line_items"), woocommerce_settings, sys_lang)
		# create_sales_order(order, woocommerce_settings, customer_name, sys_lang)
		try:
			site_domain = urlparse(order.get("_links")["self"][0]["href"]).netloc
		except Exception:
			error_message = f"{frappe.get_traceback()}\n\n Order Data: \n{str(order.as_dict())}"
			frappe.log_error("WooCommerce Error", error_message)
			raise
		custom_link_items(
			order.get("line_items"), woocommerce_settings, sys_lang, woocommerce_site=site_domain
		)
		custom_create_sales_order(order, woocommerce_settings, customer_docname, sys_lang)
		# ==================================== Custom code ends here ==================================== #


def custom_create_sales_order(order, woocommerce_settings, customer_docname, sys_lang):
	"""
	Overrided version of erpnext.erpnext_integrations.connectors.woocommerce_connection.create_sales_order
	in order to populate our custom fields when a Webhook is received
	"""
	new_sales_order = frappe.new_doc("Sales Order")
	new_sales_order.customer = customer_docname

	new_sales_order.po_no = new_sales_order.woocommerce_id = order.get("id")

	# ==================================== Custom code starts here ==================================== #
	try:
		site_domain = urlparse(order.get("_links")["self"][0]["href"]).netloc
	except Exception:
		error_message = f"{frappe.get_traceback()}\n\n Order Data: \n{str(order.as_dict())}"
		frappe.log_error("WooCommerce Error", error_message)
		raise
	new_sales_order.woocommerce_server = site_domain
	try:
		new_sales_order.woocommerce_status = WC_ORDER_STATUS_MAPPING_REVERSE[order.get("status")]
	except KeyError:
		error_message = (
			f"{frappe.get_traceback()}\n\nSales Order Data: \n{str(new_sales_order.as_dict())}"
		)
		frappe.log_error("WooCommerce Error", error_message)
		raise
	new_sales_order.woocommerce_payment_method = order.get("payment_method_title", None)
	# ==================================== Custom code ends here ==================================== #

	new_sales_order.naming_series = woocommerce_settings.sales_order_series or "SO-WOO-"

	created_date = order.get("date_created").split("T")
	new_sales_order.transaction_date = created_date[0]
	delivery_after = woocommerce_settings.delivery_after_days or 7
	new_sales_order.delivery_date = frappe.utils.add_days(created_date[0], delivery_after)

	new_sales_order.company = woocommerce_settings.company

	# ==================================== Custom code starts here ==================================== #
	# Original code
	# set_items_in_sales_order(new_sales_order, woocommerce_settings, order, sys_lang)
	custom_set_items_in_sales_order(new_sales_order, woocommerce_settings, order, sys_lang)
	# ==================================== Custom code ends here ==================================== #

	new_sales_order.flags.ignore_mandatory = True
	# ==================================== Custom code starts here ==================================== #
	# Original code
	# new_sales_order.insert()
	# new_sales_order.submit()

	submit_sales_orders = (
		frappe.get_single("WooCommerce Additional Settings").submit_sales_orders or 1
	)

	try:
		new_sales_order.insert()
		if submit_sales_orders:
			new_sales_order.submit()
	except Exception:
		error_message = (
			f"{frappe.get_traceback()}\n\nSales Order Data: \n{str(new_sales_order.as_dict())})"
		)
		frappe.log_error("WooCommerce Error", error_message)
	# ==================================== Custom code ends here ==================================== #

	# manually commit, following convention in ERPNext
	# nosemgrep
	frappe.db.commit()


def link_customer_and_address(raw_billing_data, raw_shipping_data, customer_name):
	"""
	Overrided version of erpnext.erpnext_integrations.connectors.woocommerce_connection.link_customer_and_address
	in order to handle calls to frappe.rename_doc with the same old_name and customer_name
	"""
	customer_woo_com_email = raw_billing_data.get("email")
	customer_exists = frappe.get_value("Customer", {"woocommerce_email": customer_woo_com_email})
	if not customer_exists:
		# Create Customer
		customer = frappe.new_doc("Customer")
		# ==================================== Custom code starts here ==================================== #
		customer_docname = customer_name[:3].upper() + f"{random.randrange(1, 10**3):03}"
		customer.name = customer_docname
		# ==================================== Custom code ends here ==================================== #
	else:
		# Edit Customer
		customer = frappe.get_doc("Customer", {"woocommerce_email": customer_woo_com_email})
		old_name = customer.customer_name

	customer.customer_name = customer_name
	customer.woocommerce_email = customer_woo_com_email
	customer.flags.ignore_mandatory = True

	# ==================================== Custom code starts here ==================================== #
	# Original code
	# customer.save()

	try:
		customer.save()
	except Exception:
		error_message = f"{frappe.get_traceback()}\n\nCustomer Data{str(customer.as_dict())}"
		frappe.log_error("WooCommerce Error", error_message)
	# ==================================== Custom code ends here ==================================== #

	if customer_exists:
		# ==================================== Custom code starts here ==================================== #
		# Original code commented out, we do not want to rename customers
		# frappe.rename_doc("Customer", old_name, customer_name)
		# ==================================== Custom code ends here ==================================== #
		for address_type in (
			"Billing",
			"Shipping",
		):
			try:
				address = frappe.get_doc(
					"Address", {"woocommerce_email": customer_woo_com_email, "address_type": address_type}
				)
				rename_address(address, customer)
			except (
				frappe.DoesNotExistError,
				frappe.DuplicateEntryError,
				frappe.ValidationError,
			):
				pass
	else:
		create_address(raw_billing_data, customer, "Billing")
		create_address(raw_shipping_data, customer, "Shipping")
		create_contact(raw_billing_data, customer)

	return customer.name


def custom_link_items(items_list, woocommerce_settings, sys_lang, woocommerce_site):
	"""
	Customised version of link_items to allow searching for items linked to
	multiple WooCommerce sites
	"""
	for item_data in items_list:
		item_woo_com_id = cstr(item_data.get("product_id"))

		item_codes = frappe.db.get_all(
			"Item WooCommerce Server",
			filters={"woocommerce_id": item_woo_com_id, "woocommerce_server": woocommerce_site},
			fields=["parent"],
		)
		found_item = frappe.get_doc("Item", item_codes[0].parent) if item_codes else None
		# ==================================== Custom code starts here ==================================== #
		# Original code:
		# if not frappe.db.get_value("Item", {"woocommerce_id": item_woo_com_id}, "name"):
		if not found_item:
			# ==================================== Custom code ends here ==================================== #
			# Create Item
			item = frappe.new_doc("Item")
			item.item_code = _("woocommerce - {0}", sys_lang).format(item_woo_com_id)
			item.stock_uom = woocommerce_settings.uom or _("Nos", sys_lang)
			item.item_group = _("WooCommerce Products", sys_lang)

			item.item_name = item_data.get("name")
			# ==================================== Custom code starts here ==================================== #
			# Original code:
			# item.woocommerce_id = item_woo_com_id
			row = item.append("woocommerce_servers")
			row.woocommerce_id = item_woo_com_id
			row.woocommerce_server = woocommerce_site
			# ==================================== Custom code ends here ==================================== #
			item.flags.ignore_mandatory = True
			item.save()


def custom_set_items_in_sales_order(new_sales_order, woocommerce_settings, order, sys_lang):
	"""
	Customised version of set_items_in_sales_order to allow searching for items linked to
	multiple WooCommerce sites
	"""
	company_abbr = frappe.db.get_value("Company", woocommerce_settings.company, "abbr")

	default_warehouse = _("Stores - {0}", sys_lang).format(company_abbr)
	if not frappe.db.exists("Warehouse", default_warehouse) and not woocommerce_settings.warehouse:
		frappe.throw(_("Please set Warehouse in Woocommerce Settings"))

	for item in order.get("line_items"):
		woocomm_item_id = item.get("product_id")
		# ==================================== Custom code starts here ==================================== #
		# Original code
		# found_item = frappe.get_doc("Item", {"woocommerce_id": cstr(woocomm_item_id)})
		item_codes = frappe.db.get_all(
			"Item WooCommerce Server",
			filters={
				"woocommerce_id": cstr(woocomm_item_id),
				"woocommerce_server": new_sales_order.woocommerce_server,
			},
			fields=["parent"],
		)
		found_item = frappe.get_doc("Item", item_codes[0].parent) if item_codes else None
		# ==================================== Custom code ends here ==================================== #
		ordered_items_tax = item.get("total_tax")

		new_sales_order.append(
			"items",
			{
				"item_code": found_item.name,
				"item_name": found_item.item_name,
				"description": found_item.item_name,
				"delivery_date": new_sales_order.delivery_date,
				"uom": woocommerce_settings.uom or _("Nos", sys_lang),
				"qty": item.get("quantity"),
				"rate": item.get("price"),
				"warehouse": woocommerce_settings.warehouse or default_warehouse,
			},
		)

		add_tax_details(
			new_sales_order, ordered_items_tax, "Ordered Item tax", woocommerce_settings.tax_account
		)

	# shipping_details = order.get("shipping_lines") # used for detailed order

	add_tax_details(
		new_sales_order, order.get("shipping_tax"), "Shipping Tax", woocommerce_settings.f_n_f_account
	)
	add_tax_details(
		new_sales_order,
		order.get("shipping_total"),
		"Shipping Total",
		woocommerce_settings.f_n_f_account,
	)
