import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


class BarcodeOffImportWizard(models.TransientModel):
    _name = "barcode.off.import.wizard"
    _description = "Import product by barcode from Open Food Facts"

    barcode = fields.Char(required=True)
    quantity = fields.Float(default=0.0)
    location_id = fields.Many2one(
        "stock.location",
        string="Stock Location",
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self.env.ref("stock.stock_location_stock", raise_if_not_found=False),
    )
    product_tmpl_id = fields.Many2one("product.template", readonly=True)

    def _prepare_product_name(self, product_data, barcode):
        return (
            product_data.get("product_name")
            or product_data.get("generic_name")
            or product_data.get("abbreviated_product_name")
            or barcode
        )

    def _prepare_category(self, product_data):
        category_name = False
        categories_tags = product_data.get("categories_tags") or []
        if categories_tags:
            tag = categories_tags[0]
            category_name = tag.split(":", 1)[-1].replace("-", " ").title()

        if not category_name:
            return self.env["product.category"]

        category = self.env["product.category"].search([("name", "=", category_name)], limit=1)
        if not category:
            category = self.env["product.category"].create({"name": category_name})
        return category

    def _fetch_off_product(self, barcode):
        headers = {
            # Open Food Facts can reject generic clients; identify this integration explicitly.
            "User-Agent": "ERP-BarcodeOFF/1.0 (local-dev)",
            "Accept": "application/json",
        }
        barcode_candidates = [barcode]
        if barcode.isdigit() and len(barcode) == 12:
            barcode_candidates.append(f"0{barcode}")
        if barcode.isdigit() and len(barcode) == 13 and barcode.startswith("0"):
            barcode_candidates.append(barcode[1:])

        request_error = None
        for candidate in list(dict.fromkeys(barcode_candidates)):
            urls = [
                f"https://world.openfoodfacts.org/api/v2/product/{candidate}.json",
                f"https://world.openfoodfacts.org/api/v0/product/{candidate}.json",
            ]
            for url in urls:
                try:
                    response = requests.get(url, headers=headers, timeout=12)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("status") == 1 and payload.get("product"):
                        return payload["product"]
                except requests.RequestException as exc:
                    request_error = exc

        if request_error:
            raise UserError(_("Open Food Facts request failed: %s") % request_error) from request_error
        raise UserError(_("No product found on Open Food Facts for barcode %s") % barcode)

    def _upsert_product(self, barcode, product_data):
        product = self.env["product.product"].search([("barcode", "=", barcode)], limit=1)
        name = self._prepare_product_name(product_data, barcode)
        category = self._prepare_category(product_data)

        vals = {
            "name": name,
        }
        if category:
            vals["categ_id"] = category.id

        if product:
            product.product_tmpl_id.write(vals)
            return product

        vals["type"] = "consu"
        template = self.env["product.template"].create(vals)
        template.product_variant_id.barcode = barcode
        return template.product_variant_id

    def _apply_quantity(self, product):
        if not self.quantity:
            return
        if not self.location_id:
            raise UserError(_("Please select a stock location to update quantity."))

        self.env["stock.quant"].sudo()._update_available_quantity(product, self.location_id, self.quantity)

    def action_import_from_open_food_facts(self):
        self.ensure_one()
        barcode = (self.barcode or "").strip()
        if not barcode:
            raise UserError(_("Please provide a barcode."))

        product_data = self._fetch_off_product(barcode)
        product = self._upsert_product(barcode, product_data)
        self._apply_quantity(product)
        self.product_tmpl_id = product.product_tmpl_id

        return {
            "type": "ir.actions.act_window",
            "name": _("Product"),
            "res_model": "product.template",
            "view_mode": "form",
            "res_id": product.product_tmpl_id.id,
            "target": "current",
        }
