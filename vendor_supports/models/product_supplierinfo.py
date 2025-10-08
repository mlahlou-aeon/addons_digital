# -*- coding: utf-8 -*-
from odoo import fields, models

class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    support_id = fields.Many2one('vendor.support', string='Support')
