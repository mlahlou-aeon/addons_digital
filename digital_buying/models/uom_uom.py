# -*- coding: utf-8 -*-
from odoo import fields, models

class Uom(models.Model):
    _inherit = 'uom.uom'

    _is_free = fields.Boolean(string='Gratuité')
