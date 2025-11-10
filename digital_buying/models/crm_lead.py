# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError,UserError

class CrmLead(models.Model):
    _inherit = "crm.lead"

    def action_sale_quotations_new(self):
        for order in self.order_ids:
            if order.state == 'sale':
                    raise ValidationError(_(
                        "Impossible de créer le devis : "
                        "l'opportunité '%s' possède déjà un devis validé."
                    ) % self.display_name)

        return super().action_sale_quotations_new()