# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class SaleClientPOConfirmWizard(models.TransientModel):
    _name = 'sale.client.po.wizard'
    _description = 'Wizard: Attach Client PO then Confirm'

    sale_id = fields.Many2one('sale.order', required=True, ondelete='cascade',
                              default=lambda self: self.env.context.get('default_sale_id'))
    file = fields.Binary('Fichier', required=True,
                         help="Bon de commande client")
    filename = fields.Char('Nom du fichier')

    def action_attach_and_confirm(self):
        self.ensure_one()
        if not self.file:
            # hard require a file for confirming
            raise UserError(_('Veuillez joindre le bon de commande client.'))

        # Create attachment on the sale order
        att = self.env['ir.attachment'].create({
            'name': self.filename or 'BC_Client.pdf',
            'datas': self.file,
            'res_model': 'sale.order',
            'res_id': self.sale_id.id,
            'type': 'binary',
        })

        # Post to chatter with clickable link
        self.sale_id.message_post(
            body=_("Bon de commande client joint : "
                   "<a href='#' data-oe-model='ir.attachment' data-oe-id='%s'>%s</a>") % (att.id, att.name),
            attachment_ids=[att.id],
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
