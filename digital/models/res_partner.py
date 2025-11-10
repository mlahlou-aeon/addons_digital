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
        action = self.env.ref('digital.action_vendor_support').read()[0]
        action['domain'] = [('partner_id','=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action

class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def get_application_groups(self, domain):

        product_cre = self.env.ref('product.group_product_manager')
        contact_cre = self.env.ref('base.group_partner_manager')

        domain += [('id', '!=', product_cre.id)]
        domain += [('id', '!=', contact_cre.id)]

        return super().get_application_groups(domain)
