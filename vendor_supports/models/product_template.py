# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
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
    standard_price = fields.Float("Prix d'achat",compute='_compute_cost_from_public')



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

    def _compute_cost_from_public(self):
        """Applique la règle: si support => cost = public * (1 - pct/100), sinon ne rien toucher."""
        for t in self:
            public = t.public_price or 0.0
            seller = t._get_unique_seller()
            support = seller.support_id if seller else False
            pct = (support.commission_pct or 0.0) if support else 0.0

            if support and pct:
                cost = public * (1.0 - pct / 100.0)
                if cost < 0:
                    cost = 0.0
                t.standard_price = cost
                t.list_price = public

