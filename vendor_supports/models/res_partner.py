# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    support_ids = fields.One2many('vendor.support', 'partner_id', string='Supports')
    support_count = fields.Integer(compute='_compute_support_count', string='Supports')

    def _compute_support_count(self):
        for partner in self:
            partner.support_count = len(partner.support_ids)

    def action_view_vendor_supports(self):
        self.ensure_one()
        action = self.env.ref('vendor_supports.action_vendor_support').read()[0]
        action['domain'] = [('partner_id','=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action
