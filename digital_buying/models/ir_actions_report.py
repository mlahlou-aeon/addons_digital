# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError

class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, *args, **kwargs):
        data = kwargs.get('data')
        reportname = None
        docids = None
        report_rec = None

        # Parse args
        if args:
            if isinstance(args[0], str):
                reportname = args[0]
                docids = args[1] if len(args) > 1 else None
                report_rec = self._get_report_from_name(reportname)
            else:
                docids = args[0]
                report_rec = self[0] if self else None
        else:
            reportname = kwargs.get('reportname')
            docids = kwargs.get('docids')
            if reportname:
                report_rec = self._get_report_from_name(reportname)
            else:
                report_rec = self[0] if self else None

        if isinstance(docids, (int, str)):
            try:
                docids = [int(docids)]
            except Exception:
                docids = []
        elif isinstance(docids, (list, tuple)):
            try:
                docids = [int(d) for d in docids]
            except Exception:
                docids = []
        else:
            docids = []

        model_name = (report_rec.model if report_rec else (self and self[0].model)) or ''
        if model_name.strip() == 'sale.order' and docids:
            self._guard_min_buy_before_print(docids)

        if reportname is not None:
            return super()._render_qweb_pdf(reportname, docids, data=data)
        else:
            return super()._render_qweb_pdf(docids, data=data)

    def _guard_min_buy_before_print(self, docids):
        """Block printing when a sale order is in min_buy OR draft/sent/to_validate/to_confirm and min-buy not met."""
        if not docids:
            return
        orders = self.env['sale.order'].browse(docids)
        issues = []
        for o in orders:
            if o.state == 'min_buy':
                issues.append(_("Commande %s est en état « Validation Min Buy » (min_buy).") % (o.name or o.id))
                continue
            if o.state =='draft':
                try:
                    o._check_support_min_buy_or_error()
                except UserError as e:
                    msg = e.args[0] if e.args else _("Minimum de commande non atteint.")
                    issues.append(_("Commande %s : %s") % (o.name or o.id, msg))
        if issues:
            raise UserError(_("Impression bloquée :\n%s") % "\n".join(issues))
