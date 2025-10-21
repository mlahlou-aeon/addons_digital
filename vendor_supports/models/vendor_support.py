# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class VendorSupportCategory(models.Model):
    _name = 'vendor.support.category'
    _description = 'Vendor Support Category'
    _order = 'name'

    name = fields.Char(required=True)
    description = fields.Text()


class VendorSupport(models.Model):
    _name = 'vendor.support'
    _description = 'Vendor Support'
    _order = 'name'
    _check_company_auto = True
    _inherit = ['mail.thread']

    name = fields.Char('Nom', required=True)
    partner_id = fields.Many2one('res.partner', string='Fournisseur', required=True, domain=[('supplier_rank', '>', 0)])
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one('res.currency', string='Devise', default=lambda self: self.env.company.currency_id.id)
    category_id = fields.Many2one('vendor.support.category', string='Catégorie')
    description = fields.Text('Description')
    url = fields.Char('URL')
    version_ar = fields.Boolean('AR')
    version_fr = fields.Boolean('FR')
    version_en = fields.Boolean('EN')
    media_kit = fields.Binary('Kit Média.')
    media_kit_filename = fields.Char('')
    visitors_unique = fields.Integer('Visiteurs uniques')
    sessions_per_month = fields.Integer('Sessions/mois')
    pageviews_per_month = fields.Integer('Pages vues/mois')
    avg_visit_duration = fields.Integer('Durée de visite')
    bounce_rate = fields.Float('Taux de rebond')
    social_youtube = fields.Char('YouTube')
    social_facebook = fields.Char('Facebook')
    social_instagram = fields.Char('Instagram')
    social_linkedin = fields.Char('LinkedIn')
    seg_mobile_pct = fields.Float('Mobile')
    seg_desktop_pct = fields.Float('Desktop')
    csp = fields.Selection([('A','A'), ('A+','A+'), ('B','B'), ('B+','B+')], string='CSP')
    commission_pct = fields.Float('Commission')
    campaign_commitment = fields.Selection([('none','None'), ('low','Low'), ('medium','Medium'), ('high','High')], string='Engagement sur les campagnes')
    delivery_issues = fields.Char('Problèmes de livraison')
    blacklisted = fields.Boolean('Blacklisté')
    free_tier_ids = fields.One2many('vendor.support.free.tier', 'support_id', string='Gratuités')
    minimum_buy_amount = fields.Monetary('Minimum Buy', currency_field='currency_id')
    contact_ids = fields.Many2many('res.partner', 'vendor_support_contact_rel', 'support_id', 'partner_id', string='Related Contacts')
    support_color = fields.Integer('Color Index')

    _sql_constraints = [
        ('seg_pct_valid', 'CHECK(seg_mobile_pct >= 0 AND seg_desktop_pct >= 0 AND seg_mobile_pct <= 100 AND seg_desktop_pct <= 100)', 'Segmentation percentages must be between 0 and 100.'),
        ('bounce_rate_valid', 'CHECK(bounce_rate >= 0 AND bounce_rate <= 100)', 'Bounce rate must be between 0 and 100.'),
        ('commission_valid', 'CHECK(commission_pct >= 0 AND commission_pct <= 100)', 'Commission must be between 0 and 100.'),
    ]

    @api.constrains('seg_mobile_pct', 'seg_desktop_pct')
    def _check_segmentation_sum(self):
        for rec in self:
            if rec.seg_mobile_pct and rec.seg_desktop_pct:
                if abs((rec.seg_mobile_pct + rec.seg_desktop_pct) - 100.0) > 0.5:
                    raise ValidationError(_('Mobile + Desktop percentages should be about 100%.'))


class VendorSupportFreeTier(models.Model):
    _name = 'vendor.support.free.tier'
    _description = 'Vendor Support Free Tier'
    _order = 'min_qty asc'

    support_id = fields.Many2one('vendor.support', required=True, ondelete='cascade')
    min_qty = fields.Float('Quantité', required=True)
    free_percent = fields.Float('Gratuité %', required=True)

    _sql_constraints = [
        ('free_percent_valid', 'CHECK(free_percent >= 0 AND free_percent <= 100)', 'Free % must be between 0 and 100.'),
        ('min_qty_positive', 'CHECK(min_qty >= 0)', 'Minimum quantity must be positive.'),
    ]
