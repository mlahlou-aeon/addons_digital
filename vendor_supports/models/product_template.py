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
    margin_pct = fields.Float("Marge (%)", compute='_compute_margin', store=False)
    standard_price = fields.Float(compute='_compute_cost_from_public',inverse='_inverse_standard_price',store=True,readonly=False,)

    has_support_vendor = fields.Boolean(
        string="Has Support Vendor",
        compute="_compute_has_support_vendor",
        store=True
    )

    platforme = fields.Char("Platforme")
    sub_category = fields.Many2one("product.category","Sous-catégorie",domain=[('parent_id', '!=', False)],context={'hierarchical_naming': False})

    @api.depends('seller_ids.support_id')
    def _compute_has_support_vendor(self):
        for t in self:
            # True if at least one seller has a support_id
            t.has_support_vendor = any(s.support_id for s in t.seller_ids)

    @api.constrains('valid_from', 'valid_to')
    def _check_validity_range(self):
        for p in self:
            if p.valid_from and p.valid_to and p.valid_to < p.valid_from:
                raise ValidationError(_("La date de fin doit être postérieure ou égale à la date de début."))
            
    @api.depends('list_price', 'standard_price')
    def _compute_margin(self):
        for p in self:
            p.margin_pct = ((p.list_price or 0.0) and ((p.list_price - (p.standard_price or 0.0)) / (p.list_price or 1.0) * 100.0)) or 0.0

    def _get_unique_seller(self):
        self.ensure_one()
        return self.seller_ids[:1] if self.seller_ids else False
    
    
    @api.depends('public_price', 'seller_ids.support_id', 'seller_ids.support_id.commission_pct')
    def _compute_cost_from_public(self):
        """If a seller with support exists: cost = public * (1 - pct/100).
        Else: keep whatever (manual) value was set."""
        for t in self:
            if t.has_support_vendor:
                seller = t._get_unique_seller()
                support = seller.support_id if seller else False
                pct = (support.commission_pct or 0.0) if support else 0.0

                public = t.public_price or 0.0
                cost = public * (1.0 - pct / 100.0)
                t.standard_price = max(cost, 0.0)
                t.list_price = public
            else:
                t.standard_price = t.standard_price

    def _inverse_standard_price(self):
        """Allow manual edits only when there is no support vendor."""
        for t in self:
            if t.has_support_vendor:
                raise UserError(_(
                    "Le coût est calculé automatiquement à partir du support. "
                    "Retirez le support ou modifiez la commission pour changer le coût."
                ))
