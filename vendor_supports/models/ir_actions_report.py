from odoo import models, _
from odoo.exceptions import UserError

class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, *args, **kwargs):
        data = kwargs.get('data')
        if args and isinstance(args[0], str):
            reportname, docids = args[0], (args[1] if len(args) > 1 else [])
            report_rec = self._get_report_from_name(reportname)
            report_rec._guard_min_buy_before_print(docids)
            return super(IrActionsReport, report_rec)._render_qweb_pdf(docids, data=data)

        docids = args[0] if args else []
        self._guard_min_buy_before_print(docids)
        return super()._render_qweb_pdf(docids, data=data)

    def _guard_min_buy_before_print(self, docids):
        if self.model != 'sale.order' or not docids:
            return
        orders = self.env['sale.order'].browse(docids)
        issues = []

        for o in orders:
            if o.state == 'min_buy':
                issues.append(_("Commande %s est en état « Validation Min Buy » (min_buy).") % (o.name or o.id))
                continue
            if o.state == 'draft':
                try:
                    o._check_support_min_buy_or_error()
                except UserError as e:
                    msg = e.args[0] if e.args else _("Minimum de commande non atteint.")
                    issues.append(_("Commande %s : %s") % (o.name or o.id, msg))

        if issues:
            raise UserError(_("Impression bloquée :\n%s") % "\n".join(issues))
