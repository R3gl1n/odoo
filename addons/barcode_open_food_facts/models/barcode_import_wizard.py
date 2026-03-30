import base64

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


class BarcodeOffImportWizard(models.TransientModel):
    _name = "barcode.off.import.wizard"
    _inherit = "barcodes.barcode_events_mixin"
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

    def on_barcode_scanned(self, barcode):
        self.ensure_one()
        self.barcode = (barcode or "").strip()

    def _prepare_product_name(self, product_data, barcode):
        return (
            product_data.get("product_name")
            or product_data.get("generic_name")
            or product_data.get("abbreviated_product_name")
            or barcode
        )

    def _prepare_nutrition_info(self, product_data):
        """Extract nutritional values from OFF product data."""
        nutrition = product_data.get("nutriments", {})
        if not nutrition:
            return False
        
        lines = []
        # Typical nutrition facts per 100g
        energy = nutrition.get("energy-kcal_100g")
        fat = nutrition.get("fat_100g")
        carbs = nutrition.get("carbohydrates_100g")
        protein = nutrition.get("proteins_100g")
        salt = nutrition.get("salt_100g")
        fiber = nutrition.get("fiber_100g")
        
        if energy:
            lines.append(_("Energy: %.0f kcal/100g") % energy)
        if fat:
            lines.append(_("Fat: %.1f g/100g") % fat)
        if carbs:
            lines.append(_("Carbs: %.1f g/100g") % carbs)
        if protein:
            lines.append(_("Protein: %.1f g/100g") % protein)
        if salt:
            lines.append(_("Salt: %.2f g/100g") % salt)
        if fiber:
            lines.append(_("Fiber: %.1f g/100g") % fiber)
        
        if not lines:
            return False
        return "\n".join(lines)

    def _prepare_description_sale(self, product_data):
        # Combine ingredients and nutrition info
        ingredients_text = product_data.get("ingredients_text")
        nutrition_info = self._prepare_nutrition_info(product_data)
        
        parts = []
        if ingredients_text:
            parts.append(_("Ingredients:\n%s") % ingredients_text.strip())
        if nutrition_info:
            parts.append(_("Nutrition Facts (per 100g):\n%s") % nutrition_info)
        
        if not parts:
            return False
        return "\n\n".join(parts)

    def _prepare_internal_description(self, product_data):
        lines = []
        brands = product_data.get("brands")
        quantity_text = product_data.get("quantity")
        nutriscore = product_data.get("nutriscore_grade")
        nova_group = product_data.get("nova_group")
        ecoscore = product_data.get("ecoscore_grade")
        manufacturers = product_data.get("manufacturers")
        origins = product_data.get("countries_tags") or []
        labels = product_data.get("labels_tags") or []
        allergens = product_data.get("allergens") or product_data.get("allergens_from_ingredients")

        if brands:
            lines.append(_("Brand: %s") % brands)
        if quantity_text:
            lines.append(_("Package Quantity: %s") % quantity_text)
        if manufacturers:
            lines.append(_("Manufacturer: %s") % manufacturers)
        if origins:
            origin_str = ", ".join([o.replace("-", " ").title() for o in origins[:3]])
            lines.append(_("Origin: %s") % origin_str)
        if nutriscore:
            lines.append(_("Nutri-Score: %s") % str(nutriscore).upper())
        if ecoscore:
            lines.append(_("Eco-Score: %s") % str(ecoscore).upper())
        if nova_group:
            lines.append(_("NOVA Group: %s") % nova_group)
        if allergens:
            lines.append(_("Allergens: %s") % allergens)
        if labels:
            label_str = ", ".join([l.replace("-", " ").title() for l in labels[:5]])
            lines.append(_("Labels/Certifications: %s") % label_str)

        if not lines:
            return False
        return "\n".join(lines)

    def _prepare_logistics_vals(self, product_data):
        quantity = product_data.get("product_quantity")
        unit = (product_data.get("product_quantity_unit") or "").strip().lower()
        if quantity in (None, False):
            return {}

        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            return {}

        vals = {}
        if unit == "g":
            vals["weight"] = quantity / 1000.0
        elif unit == "kg":
            vals["weight"] = quantity
        elif unit == "ml":
            vals["volume"] = quantity / 1_000_000.0
        elif unit == "cl":
            vals["volume"] = quantity / 100_000.0
        elif unit == "dl":
            vals["volume"] = quantity / 10_000.0
        elif unit == "l":
            vals["volume"] = quantity / 1000.0
        return vals

    def _prepare_image_1920(self, product_data):
        image_url = product_data.get("image_front_url") or product_data.get("image_url")
        if not image_url:
            return False

        headers = {
            "User-Agent": "ERP-BarcodeOFF/1.0 (local-dev)",
            "Accept": "image/*",
        }
        try:
            response = requests.get(image_url, headers=headers, timeout=12)
            response.raise_for_status()
        except requests.RequestException:
            return False

        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type:
            return False

        return base64.b64encode(response.content)

    def _prepare_product_vals(self, barcode, product_data):
        name = self._prepare_product_name(product_data, barcode)
        category = self._prepare_category(product_data)

        vals = {
            "name": name,
            "default_code": barcode,
            "description_sale": self._prepare_description_sale(product_data),
            "description": self._prepare_internal_description(product_data),
        }
        if category:
            vals["categ_id"] = category.id

        vals.update(self._prepare_logistics_vals(product_data))

        image_1920 = self._prepare_image_1920(product_data)
        if image_1920:
            vals["image_1920"] = image_1920

        return vals

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
        return False

    def _upsert_fallback_product(self, barcode):
        product = self.env["product.product"].search([("barcode", "=", barcode)], limit=1)
        if product:
            return product

        template = self.env["product.template"].create({
            "name": _("Unknown Product (%s)") % barcode,
            "default_code": barcode,
            "description": _("Automatically created because no Open Food Facts match was found."),
            "type": "consu",
        })
        template.product_variant_id.barcode = barcode
        return template.product_variant_id

    def _upsert_product(self, barcode, product_data):
        product = self.env["product.product"].search([("barcode", "=", barcode)], limit=1)
        vals = self._prepare_product_vals(barcode, product_data)

        if product:
            template = product.product_tmpl_id
            update_vals = {
                "name": vals["name"],
                "categ_id": vals.get("categ_id"),
            }
            optional_fields = [
                "default_code",
                "description",
                "description_sale",
                "weight",
                "volume",
                "image_1920",
            ]
            for field_name in optional_fields:
                if vals.get(field_name) and not template[field_name]:
                    update_vals[field_name] = vals[field_name]
            update_vals = {key: value for key, value in update_vals.items() if value is not None}
            template.write(update_vals)
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
        if product_data:
            product = self._upsert_product(barcode, product_data)
        else:
            product = self._upsert_fallback_product(barcode)
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
