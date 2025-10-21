{
    "name": "Vendor Supports Management",
    "summary": "Manage supports per supplier",
    "version": "18.0.1.0.0",
    "category": "Purchases",
    "author": "DarbTech Labs",
    "license": "LGPL-3",
    "depends": [
        "base",
        "contacts",
        "purchase",
        "sale_management",
        "product"
    ],
    "data": [
        "security/vendor_supports_security.xml",
        "security/ir.model.access.csv",
        "views/vendor_support_views.xml",
        "views/res_partner_views.xml",
        "views/purchase_views.xml",
        "views/product_supplierinfo_views.xml",
        "views/product_template_view.xml",
        "views/sale_order_view.xml",
        "wizard/bc_client_view.xml",
        "data/support_category_data.xml",
    ],
    "installable": True,
    "application": True
}