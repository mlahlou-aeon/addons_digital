# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    sale_id = fields.Many2one("sale.order", string="Source Sale Order", index=True)

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    support_id = fields.Many2one(
        'vendor.support',
        string='Support',
        domain="[('id', 'in', available_support_ids)]",
        help="Support linked to this product for the selected vendor."
    )
    available_support_ids = fields.Many2many(
        'vendor.support',
        compute='_compute_available_supports',
        string='Available Supports',
        compute_sudo=True,
    )
    has_available_supports = fields.Boolean(
        compute='_compute_available_supports',
    )

    @api.depends('product_id', 'order_id.partner_id')
    def _compute_available_supports(self):
        """Restrict supports by both product (variant or template) and the PO vendor."""
        lines = self.filtered(lambda l: l.product_id and l.order_id.partner_id)
        others = self - lines
        # Default for lines without enough context
        for l in others:
            l.available_support_ids = False
            l.has_available_supports = False

        if not lines:
            return

        # Batch query supplierinfo once
        SupplierInfo = self.env['product.supplierinfo']
        prod_ids = lines.mapped('product_id').ids
        tmpl_ids = lines.mapped('product_id.product_tmpl_id').ids
        vendor_ids = lines.mapped('order_id.partner_id').ids

        sis = SupplierInfo.search([
            ('support_id', '!=', False),
            ('partner_id', 'in', vendor_ids),
            '|', ('product_id', 'in', prod_ids),
                 ('product_tmpl_id', 'in', tmpl_ids),
        ])

        # Index supports by (variant, vendor) and (template, vendor)
        by_variant_vendor = {}
        by_template_vendor = {}
        for si in sis:
            v_id = si.partner_id.id
            if si.product_id:
                key = (si.product_id.id, v_id)
                by_variant_vendor.setdefault(key, set()).add(si.support_id.id)
            else:
                key = (si.product_tmpl_id.id, v_id)
                by_template_vendor.setdefault(key, set()).add(si.support_id.id)

        for l in lines:
            v_id = l.order_id.partner_id.id
            s_ids = set()
            s_ids |= set(by_variant_vendor.get((l.product_id.id, v_id), set()))
            s_ids |= set(by_template_vendor.get((l.product_id.product_tmpl_id.id, v_id), set()))
            l.available_support_ids = [(6, 0, list(s_ids))]
            l.has_available_supports = bool(s_ids)

            # Drop invalid support if product/vendor changed
            if l.support_id and l.support_id.id not in s_ids:
                l.support_id = False

    @api.onchange('product_id', 'order_id.partner_id')
    def _onchange_prefill_support(self):
        """Optional: prefill if exactly one support fits."""
        if self.product_id and self.order_id.partner_id and self.available_support_ids and len(self.available_support_ids) == 1:
            self.support_id = self.available_support_ids[:1]

