# models/sale_min_buy_wizard.py
from odoo import api, fields, models, _

MIN_BUY_GROUP_XMLID = 'digital.group_min_buy_approver'

class SaleMinBuyWizard(models.TransientModel):
    _name = 'sale.min.buy.wizard'
    _description = 'Validation Min Buy - Wizard'

    sale_id = fields.Many2one('sale.order', required=True, ondelete='cascade')
    errors_text = fields.Text(readonly=True)
    reason = fields.Text(string="Motif (optionnel)")

    def action_request_validation(self):
        self.ensure_one()
        o = self.sale_id.sudo()

        o.write({'state': 'min_buy'})
        o.message_post(body=_("Validation Min Buy demandée.") + (
            ("\n" + _("Motif : %s") % self.reason.strip()) if self.reason else ""
        ))

        # Notify approvers
        """grp = self.env.ref(MIN_BUY_GROUP_XMLID, raise_if_not_found=False)
        if grp and grp.users:
            for u in grp.users:
                o.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=u.id,
                    note=_("Commande %s : validation Min Buy requise.") % o.name
                )"""
        
        return {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
