# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError,UserError
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from odoo.tools import float_round, float_is_zero, float_compare

SALE_ORDER_STATE = [
    ('draft', "Devis"),
    ('sent', "Envoyé"),
    ('to_validate', 'À valider'),
    ('to_confirm', 'À confirmer'),
    ('sale', "Commande"),
    ('cancel', "Annulé"),
]

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_open_purchase_order(self):
        tree_id = self.env.ref("purchase.purchase_order_kpis_tree").id
        form_id = self.env.ref("purchase.purchase_order_form").id
        return {
            "name": _("Requests for Quotation"),
            "view_mode": "list,form",
            'views': [(tree_id, 'list'),(form_id,'form')],
            "res_model": "purchase.order",
            "domain":[('origin', '=', self.name)],
            "type": "ir.actions.act_window",
            "target": "current",
        }

    def _get_po(self):
        for orders in self:
            purchase_ids = self.env['purchase.order'].sudo().search([('origin', '=', self.name)])
        orders.purchase_order_count = len(purchase_ids)

    start_date = fields.Date("Date début")
    end_date = fields.Date("Date fin")
    purchase_order_count = fields.Integer(
        string="Purchase Orders",
        compute="_get_po",
    )

    state = fields.Selection(selection=SALE_ORDER_STATE,
        string="Status",
        readonly=True, copy=False, index=True,
        tracking=3,
        default='draft')

    approval_required_level = fields.Selection(
        [('none', 'Aucune'), ('n1', 'Approbation N+1'), ('n2', 'Approbation N+1 & N+2')],
        string="Niveau d’approbation requis", compute="_compute_approval_required_level", store=True
    )

    @api.depends(
        "order_line.commission_pct",
        "order_line.support_id", "order_line.support_id.commission_pct",
        "amount_total",
    )
    def _compute_approval_required_level(self):
        for o in self:
            lines = o.order_line.filtered(lambda l: (l.product_uom_qty or 0.0) > 0.0)

            any_line_over_15 = any((l.commission_pct or 0.0) > 15.0 for l in lines)
            any_line_over_agency = any(
                (l.commission_pct or 0.0) > (getattr(l.support_id, 'commission_pct', 0.0) or 0.0)
                for l in lines
            )
            over_budget = (o.amount_total or 0.0) > 500000.0

            if any_line_over_15 or over_budget or any_line_over_agency:
                o.approval_required_level = 'n2'
            else:
                o.approval_required_level = 'n1'
    
    def action_request_approval(self):
        """Move draft/sent to 'to_validate' and log the request."""
        for o in self:
            if o.state not in ('draft', 'sent'):
                raise UserError(_("Only draft/sent quotations can be submitted for approval."))
            o.write({'state': 'to_validate'})
            o.message_post(body=_("Approval requested (level: %s).") % (o.approval_required_level.upper()))
        return True

    def action_approve(self):
        self.ensure_one()
        o = self
        if o.state not in ('to_validate', 'to_confirm'):
            raise UserError(_("This quotation is not awaiting approval."))

        if o.approval_required_level == 'n1':
            o._require_group("vendor_supports.group_quote_approve_n1")
            o.message_post(body=_("Approved by N+1. Confirmation executed."))
            o.action_confirm()

        # N+2 path
        if o.state == 'to_validate':
            # First approval must be N+1, then go to 'to_confirm'
            o._require_group("vendor_supports.group_quote_approve_n1")
            o.write({'state': 'to_confirm'})
            o.message_post(body=_("Approved by N+1. Moved to 'To confirm' (awaiting N+2)."))
            return True

        if o.state == 'to_confirm':
            # Second approval must be N+2, then confirm
            o._require_group("vendor_supports.group_quote_approve_n2")
            o.message_post(body=_("Approved by N+2. Confirmation executed."))
            o.action_confirm()
    
    def _require_group(self, xmlid):
        if not self.env.user.has_group(xmlid):
            raise UserError(_("You don't have permission to perform this approval."))

    """@api.onchange('order_line')
    def _onchange_check_support_min_buy(self):
        if not self.order_line:
            return

        # Cumul des sous-totaux par support, convertis en devise société
        company = self.company_id or self.env.company
        company_cur = company.currency_id
        cumuls = defaultdict(float)

        for line in self.order_line:
            if not line.support_id:
                continue
            # price_subtotal est en devise du devis (line.currency_id)
            amount_company = line.currency_id._convert(
                line.price_total, company_cur, company,
                self.date_order or fields.Date.context_today(self)
            )
            cumuls[line.support_id] += amount_company

        alerts = []
        for support, subtotal in cumuls.items():
            if support.minimum_buy_amount and subtotal <= support.minimum_buy_amount:
                alerts.append(
                    f"- {support.display_name}: total {company_cur.symbol} {subtotal:,.2f} "
                    f"≤ minimum {company_cur.symbol} {support.minimum_buy_amount:,.2f}".replace(',', ' ')
                )

        if alerts:
            return {
                'warning': {
                    'title': "Minimum buy non atteint",
                    'message': "\n".join(alerts),
                }
            }
        """
    def _check_support_min_buy_or_error(self):
        company = self.company_id or self.env.company
        company_cur = company.currency_id

        for order in self:
            cumuls = defaultdict(float)
            for line in order.order_line:
                if not line.support_id:
                    continue
                amount_company = line.currency_id._convert(
                    line.price_total, company_cur, order.company_id,
                    order.date_order or fields.Date.context_today(order)
                )
                cumuls[line.support_id] += amount_company

            errors = []
            for support, subtotal in cumuls.items():
                if support.minimum_buy_amount and subtotal <= support.minimum_buy_amount:
                    errors.append(
                        f"{support.display_name}: {company_cur.symbol} {subtotal:,.2f} "
                        f"≤ {company_cur.symbol} {support.minimum_buy_amount:,.2f}".replace(',', ' ')
                    )
            if errors:
                raise UserError(
                    "Minimum de commande par support non atteint :\n" + "\n".join(errors)
                )

    # ---- Auto-create POs on confirm (keep your existing logic if you have one) ----
    def action_confirm(self):
        for order in self:
            if order.approval_required_level == 'n1' and order.state not in ('to_validate','draft','sent'):
                raise UserError(_("Le devis doit être en état 'À valider' pour une confirmation N+1."))
            if order.approval_required_level == 'n2' and order.state != 'to_confirm':
                raise UserError(_("Le devis doit être en état 'À confirmer' pour une confirmation N+2."))
        res = super().action_confirm()
        for order in self:
            order._check_support_min_buy_or_error()
            order._create_purchase_orders_from_so()
            if len(order) == 1:
                return {
                    'name': _('Joindre le BC Client'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'sale.client.po.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_sale_id': order.id},
                }
        return res

    def _create_purchase_orders_from_so(self):
        self.ensure_one()
        PurchaseOrder = self.env["purchase.order"]
        PurchaseOrderLine = self.env["purchase.order.line"]

        grouped = {}
        for line in self.order_line:
            if not line.product_id:
                continue
            vendor, seller = self._get_vendor_and_seller_for_line(line)
            if not vendor:
                continue
            grouped.setdefault(vendor.id, []).append((line, seller))

        if not grouped:
            return

        created_pos = []
        for partner_id, pairs in grouped.items():
            if line.product_id.product_kind != 'external':
                continue
            
            vendor = self.env["res.partner"].browse(partner_id)
            # ensure PO is created in SO company (multi-company safety)
            po = PurchaseOrder.with_company(self.company_id).create({
                "partner_id": vendor.id,
                "company_id": self.company_id.id,
                "origin": self.name,
                "sale_id": self.id,                # <-- CRUCIAL for the smart button
                # currency, picking_type_id can be defaulted
            })
            for so_line, seller in pairs:
                po_uom = (seller and seller.product_uom) or so_line.product_id.uom_po_id or so_line.product_uom
                qty = so_line.product_uom._compute_quantity(so_line.product_uom_qty, po_uom)

                taxes = so_line.product_id.supplier_taxes_id.filtered(lambda t: t.company_id == po.company_id)
                date_planned = fields.Datetime.now()

                PurchaseOrderLine.create({
                    "order_id": po.id,
                    "product_id": so_line.product_id.id,
                    "support_id": so_line.support_id.id,
                    "name": so_line.name or so_line.product_id.display_name,
                    "product_qty": qty,
                    "product_uom": po_uom.id,
                    "price_unit": so_line.purchase_price,
                    "date_planned": date_planned,
                    "taxes_id": [(6, 0, taxes.ids)],
                })
            created_pos.append(po)
            po.button_confirm()


    def _get_vendor_and_seller_for_line(self, line):
        product = line.product_id
        vendor = getattr(product.product_tmpl_id, "vendor_id", False) or False

        seller = product._select_seller(
            partner_id=vendor,
            quantity=line.product_uom_qty,
            date=self.date_order or fields.Date.context_today(self),
            uom_id=line.product_uom,
        )
        if not vendor:
            vendor = seller.partner_id if seller else False
        return vendor, seller
    
    def _get_support_discount_product(self):
        Product = self.env['product.product'].sudo()
        prod = Product.search([('default_code', '=', 'SUPPORT_DISCOUNT')], limit=1)
        if not prod:
            prod = Product.create({
                'name': 'Gratuité',
                'default_code': 'SUPPORT_DISCOUNT',
                'type': 'service',
                'list_price': 0.0,
                'taxes_id': [(6, 0, [])],
                'sale_ok': True,
                'purchase_ok': False,
            })
        return prod
    
    def _recompute_support_discount_lines(self):
        """Grant free quantities per support, using the discount product for generated lines."""
        for order in self:
            currency = order.currency_id
            discount_product = order._get_support_discount_product()

            # Source lines: real items with support, excluding already generated lines
            src_lines = order.order_line.filtered(
                lambda l: not l.display_type
                        and not l.is_support_discount_line
                        and l.support_id
            )

            # Group source lines by support
            by_support = defaultdict(list)
            for l in src_lines:
                by_support[l.support_id].append(l)

            # Index existing generated lines by (support_id, original_product_id, original_uom_id)
            existing = {}
            for l in order.order_line.filtered(lambda l: l.is_support_discount_line and not l.display_type):
                # We encode the original product/uom in the name, but key by support + name to be safe
                # Prefer storing a hidden field if you want stronger linkage
                key = (l.support_id.id, l.name)
                existing[key] = l

            supports_seen = set()

            for support, lines in by_support.items():
                supports_seen.add(support.id)

                # Determine free % (best tier by total qty)
                total_qty = sum(l.product_uom_qty for l in lines)
                tiers = support.free_tier_ids.filtered(lambda t: total_qty >= (t.min_qty or 0.0))
                if tiers:
                    best = tiers.sorted(key=lambda t: t.min_qty)[-1]
                    rate = (best.free_percent or 0.0) / 100.0
                else:
                    rate = 0.0

                # Desired free qty per (original product, original uom), rounding DOWN
                desired_map = defaultdict(float)  # (prod_id, uom_id) -> free_qty
                for l in lines:
                    if rate <= 0 or float_is_zero(l.product_uom_qty, precision_rounding=l.product_uom.rounding):
                        continue
                    free_qty = float_round(
                        l.product_uom_qty * rate,
                        precision_rounding=l.product_uom.rounding,
                        rounding_method='DOWN',
                    )
                    if not float_is_zero(free_qty, precision_rounding=l.product_uom.rounding):
                        desired_map[(l.product_id.id, l.product_uom.id)] += free_qty

                # Create/update zero-priced lines using the discount product
                desired_keys_for_cleanup = set()
                for (orig_prod_id, orig_uom_id), desired_free_qty in desired_map.items():
                    # Line label carries support + original product reference for clarity
                    line_name = f"Gratuité {support.display_name}"

                    key = (support.id, line_name)
                    desired_keys_for_cleanup.add(key)
                    free_line = existing.get(key)

                    if free_line:
                        # Update qty if changed (UoM is that of the line, we keep it consistent)
                        if float_compare(
                            free_line.product_uom_qty, desired_free_qty,
                            precision_rounding=free_line.product_uom.rounding
                        ) != 0:
                            free_line.with_context(skip_support_discount=True).write({
                                'product_uom_qty': desired_free_qty,
                                'name': line_name,
                                'price_unit': 0.0,
                                'discount': 0.0,
                                'tax_id': [(6, 0, [])],
                            })
                    else:
                        # Create a new zero-price line with the discount product
                        order_id = self.env['sale.order'].search([('name','=',order.name)])
                        self.env['sale.order.line'].with_context(skip_support_discount=True).create({
                            'order_id': order_id.id,
                            'product_id': discount_product.id,
                            'product_uom': orig_uom_id,         # keep the original UoM bucket
                            'product_uom_qty': desired_free_qty,
                            'price_unit': 0.0,                  # free
                            'discount': 0.0,
                            'tax_id': [(6, 0, [])],             # no taxes on free qty
                            'name': line_name,
                            'is_support_discount_line': True,
                        })

                # Remove obsolete generated lines for this support
                for (sup_id, name), line in list(existing.items()):
                    if sup_id == support.id and (sup_id, name) not in desired_keys_for_cleanup:
                        line.with_context(skip_support_discount=True).unlink()

            # Cleanup: remove generated lines whose support vanished
            for line in order.order_line.filtered(lambda l: l.is_support_discount_line and not l.display_type):
                if line.support_id and line.support_id.id not in supports_seen:
                    line.with_context(skip_support_discount=True).unlink()

    @api.onchange('order_line')
    def _onchange_support_discount(self):
        if self.env.context.get('skip_support_discount'):
            return
        self._recompute_support_discount_lines()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    support_id = fields.Many2one(
        'vendor.support',
        string='Support',
        domain="[('id', 'in', available_support_ids)]",
        help="Support available for the selected product (derived from vendor pricelists).",
    )
    commission_pct = fields.Float('Commission',compute='_compute_commission_pct',store=True,)
    available_support_ids = fields.Many2many(
        'vendor.support',
        compute='_compute_available_supports',
        string='Available Supports',
        compute_sudo=True,
    )
    has_available_supports = fields.Boolean(
        compute='_compute_available_supports',
    )

    public_price = fields.Float(
    related='product_id.product_tmpl_id.public_price',
    string="Prix public",
    store=False, readonly=True
    )
    is_support_discount_line = fields.Boolean(
        string='Ligne remise (support)', default=False, copy=False, index=True,
        help="Ligne de remise générée automatiquement depuis la grille du Support."
    )

    @api.depends(
        'price_unit',
        'purchase_price',
        'support_id.commission_pct'
    )
    def _compute_commission_pct(self):
        """
        commission (%) = (price_unit - cost_in_order_currency) / price_unit * 100
        Fallback to support's default when we cannot compute.
        """
        for line in self:
            # default from support
            fallback = float(line.support_id.commission_pct or 0.0)

            price = float(line.price_unit or 0.0)
            cost_company = float(line.purchase_price or 0.0)  # in company currency on SOL
            if price <= 0:
                line.commission_pct = fallback
                continue

            pct = (price - line.purchase_price) / price * 100.0 if price > 0 else 0.0
            # if nothing meaningful (e.g., cost not set), keep support default
            line.commission_pct = round(pct, 2) if (cost_company > 0.0) else fallback

    @api.depends('product_id')
    def _compute_available_supports(self):
        # Batch compute for all lines with a product
        lines = self.filtered('product_id')
        if not lines:
            self.available_support_ids = False
            self.has_available_supports = False
            return

        # Build indexes of supports by variant and by template
        ProductSupplierInfo = self.env['product.supplierinfo']
        prod_ids = lines.mapped('product_id').ids
        tmpl_ids = lines.mapped('product_id.product_tmpl_id').ids

        sis = ProductSupplierInfo.search([
            '|', ('product_id', 'in', prod_ids),
                 ('product_tmpl_id', 'in', tmpl_ids),
            ('support_id', '!=', False),
        ])

        by_variant = {}
        by_template = {}
        for si in sis:
            if si.product_id:
                by_variant.setdefault(si.product_id.id, set()).add(si.support_id.id)
            else:
                by_template.setdefault(si.product_tmpl_id.id, set()).add(si.support_id.id)

        for line in self:
            if not line.product_id:
                line.available_support_ids = False
                line.has_available_supports = False
                continue
            s_ids = set()
            # union supports defined at variant and template level
            s_ids |= set(by_variant.get(line.product_id.id, set()))
            s_ids |= set(by_template.get(line.product_id.product_tmpl_id.id, set()))
            line.available_support_ids = [(6, 0, list(s_ids))]
            line.has_available_supports = bool(s_ids)

            # If a support is set but not valid for this product, clear it
            if line.support_id and line.support_id.id not in s_ids:
                line.support_id = False

    @api.onchange('product_id')
    def _onchange_product_id_support_prefill(self):
        """Optional: if exactly one support is available for the chosen product, prefill it."""
        if self.product_id and self.available_support_ids and len(self.available_support_ids) == 1:
            self.support_id = self.available_support_ids[:1]


    @api.depends('product_id', 'company_id', 'currency_id', 'product_uom')
    def _compute_purchase_price(self):
        for line in self:
            if not line.product_id:
                line.purchase_price = 0.0
                continue
            line.purchase_price = line.product_id.standard_price