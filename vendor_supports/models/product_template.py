# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError,UserError
from datetime import date

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    product_kind = fields.Selection([
        ('internal', 'Interne'),
        ('external', 'Externe'),
        ('international', 'International'),
        ('adserving', 'AdServing'),
    ], "Type")

    public_price = fields.Float("Prix public unitaire")
    display_scope = fields.Selection([('desktop', 'Desktop'), ('mobile', 'Mobile'), ('multi', 'Multi-device')], "Affichage")
    ras = fields.Boolean("RAS")
    valid_from = fields.Date("Date de début")
    valid_to = fields.Date("Date de fin")
    margin_pct = fields.Float("Commission (%)", compute='_compute_margin', store=False)
    standard_price = fields.Float(compute='_compute_cost_from_public',store=True,readonly=False,compute_sudo=True)
    sub_category = fields.Many2one("product.category","Sous-catégorie",domain=[('parent_id', '!=', False)])
    support_id = fields.Many2one("vendor.support")

    @api.model
    def create(self, vals):
        support_id = vals.get('support_id') or self.env.context.get('default_support_id')
        if support_id:
            support = self.env['vendor.support'].browse(support_id).exists()
            if support:
                vals.setdefault('support_id', support.id)
                vals['categ_id'] = self.env.ref('vendor_supports.product_category_premium').id
                vals['list_price'] = vals['public_price']

                if not vals.get('seller_ids') and support.partner_id:
                    vals['seller_ids'] = [(0, 0, {
                        'partner_id': support.partner_id.id,
                        'support_id': support.id,
                    })]
        return super().create(vals)
    
    def _determine_support_from_sellers(self):
        self.ensure_one()
        for s in self.seller_ids:
            if hasattr(s, 'support_id') and s.support_id:
                return s.support_id
        for s in self.seller_ids:
            partner = getattr(s, 'partner_id', False)
            if partner:
                supp = self.env['vendor.support'].search([('partner_id', '=', partner.id)], limit=2)
                if len(supp) == 1:
                    return supp

        return self.env['vendor.support']  
    
    @api.onchange('seller_ids')
    def _onchange_sync_support_with_sellers(self):
        for p in self:
            if not p.seller_ids:
                p.support_id = False
            else:
                new_support = p._determine_support_from_sellers()
                if new_support:
                    p.support_id = new_support

    def write(self, vals):
        res = super().write(vals)
        if 'seller_ids' in vals:
            for p in self:
                if not p.seller_ids:
                    if p.support_id:
                        p.with_context(allow_cost_write=True).write({'support_id': False})
                else:
                    new_support = p._determine_support_from_sellers()
                    if new_support and p.support_id != new_support:
                        p.with_context(allow_cost_write=True).write({'support_id': new_support.id})
        return res

    @api.constrains('valid_from', 'valid_to')
    def _check_validity_range(self):
        for p in self:
            if p.valid_from and p.valid_to and p.valid_to < p.valid_from:
                raise ValidationError(_("La date de fin doit être postérieure ou égale à la date de début."))
            
    @api.depends('list_price', 'standard_price')
    def _compute_margin(self):
        for p in self:
            p.margin_pct = ((p.list_price or 0.0) and ((p.list_price - (p.standard_price or 0.0)) / (p.list_price or 1.0) * 100.0)) or 0.0
    
    @api.depends('public_price', 'support_id', 'support_id.commission_pct')
    def _compute_cost_from_public(self):
        for t in self:
            if t.support_id:
                pct = t.support_id.commission_pct or 0.0
                public = t.public_price or 0.0
                cost = public * (1.0 - pct / 100.0)
                t.standard_price = max(cost, 0.0)
                t.list_price = public
            else:
                t.list_price = t.public_price