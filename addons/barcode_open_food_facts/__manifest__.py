{
    "name": "Barcode Open Food Facts",
    "version": "19.0.1.0.0",
    "summary": "Import products by barcode from Open Food Facts",
    "author": "ERP Team",
    "license": "LGPL-3",
    "depends": ["product", "stock", "barcodes"],
    "data": [
        "security/ir.model.access.csv",
        "views/barcode_import_wizard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "barcode_open_food_facts/static/src/js/barcode_auto_import.js",
        ],
    },
    "installable": True,
    "application": True,
}
