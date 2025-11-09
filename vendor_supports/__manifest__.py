{
    "name": "Vendor Supports Management",
    "summary": "Manage supports per supplier",
    "version": "19.0.1.0.0",
    "category": "Purchases",
    "author": "AEON",
    "license": "LGPL-3",
    "depends": [
        "base",
        "contacts",
        "purchase",
        "sale",
        "crm",
        "sale_management",
        "product",
        "sale_margin",
        "account"
    ],
    "data": [
        "data/support_category_data.xml",
        "security/vendor_supports_security.xml",
        "security/ir.model.access.csv",
        "views/vendor_support_views.xml",
        "views/res_partner_views.xml",
        "views/purchase_views.xml",
        "views/product_supplierinfo_views.xml",
        "views/product_template_view.xml",
        "views/sale_order_view.xml",
        "views/account_form_view.xml",
        "wizard/bc_client_view.xml",
        "wizard/min_buy_wizard_view.xml",
    ],
    'assets': {
    'web.assets_backend': [
        'vendor_supports/static/src/xml/sale_onboarding_list_renderer.xml',
    ],
},

    "installable": True,
    "application": True
}