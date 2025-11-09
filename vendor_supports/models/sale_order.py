# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError,UserError
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from odoo.tools import float_round, float_is_zero, float_compare

SALE_ORDER_STATE = [
    ('draft', "Devis"),
    ('sent', "Envoyé"),
    ('min_buy', 'Validation Min Buy'),
    ('to_validate', 'À valider'),
    ('to_confirm', 'À confirmer'),
    ('sale', "Commande"),
    ('cancel', "Annulé"),
]

GROUP_N1 = "vendor_supports.group_quote_approve_n1"
GROUP_N2 = "vendor_supports.group_quote_approve_n2"
MIN_BUY_GROUP_XMLID = "vendor_supports.group_min_buy_approver"

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


    def action_confirm(self):
        for order in self:
            if order.approval_required_level == 'n1' and order.state not in ('to_validate','draft','sent'):
                raise UserError(_("Le devis doit être en état 'À valider' pour une confirmation N+1."))
            if order.approval_required_level == 'n2' and order.state != 'to_confirm':
                raise UserError(_("Le devis doit être en état 'À confirmer' pour une confirmation N+2."))
        res = super().action_confirm()
        for order in self:
            order._create_purchase_orders_from_so()
            order.opportunity_id.action_set_won_rainbowman()
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
    
    def action_set_to_draft(self):
        for o in self:
            o.write({'state': 'draft'})

    
    def action_approve(self):
        self.ensure_one()
        o = self

        if o.state not in ('to_validate', 'to_confirm'):
            raise UserError(_("Ce devis n’est pas en attente d’approbation."))

        if o.state == 'to_validate':
            o._require_group(GROUP_N1)

            if o.approval_required_level == 'n1':
                return o.action_confirm()
            o.write({'state': 'to_confirm'})
            o.message_post(body=_("Approbation N1 effectuée. Passage à l'approbation N2."))
            return True

        if o.state == 'to_confirm':
            if o.approval_required_level == 'n1':
                o._require_group(GROUP_N1)
            else:
                o._require_group(GROUP_N2)
            return o.action_confirm()

        raise UserError(_("État d’approbation non géré."))

    def action_request_approval(self):
        for o in self:
            if o.state in ('draft', 'sent'):
                errors = o._check_support_min_buy_or_error(raise_exception=False)
                if errors:
                    return o._open_min_buy_wizard(
                        "Minimum de commande par support non atteint :\n" + "\n".join(errors)
                    )
                if o.approval_required_level == 'n1':
                    o.write({'state': 'to_confirm'})
                    o.message_post(body=_("Demande d’approbation (N1 uniquement)."))
                else:
                    o.write({'state': 'to_validate'})
                    o.message_post(body=_("Demande d’approbation (N1 puis N2)."))
                continue

            if o.state == 'min_buy':
                if self.env.user.has_group(MIN_BUY_GROUP_XMLID):
                    next_state = 'to_confirm' if o.approval_required_level == 'n1' else 'to_validate'
                    o.write({'state': next_state})
                    continue
                raise UserError(_("Cette commande est en 'Validation Min Buy'. "
                                  "Seul un approbateur Min Buy peut la soumettre en 'À valider'."))

            raise UserError(_("Seuls les devis en brouillon/envoyés peuvent être soumis pour approbation."))
        return True

    @api.depends(
        "order_line.commission_pct",
        "order_line.support_id", "order_line.support_id.commission_pct",
        "amount_total",
    )
    def _compute_approval_required_level(self):
        for o in self:
            lines = o.order_line.filtered(lambda l: (l.product_uom_qty or 0.0) > 0.0 and not l.is_free_line)

            any_line_under_15 = any((l.commission_pct or 0.0) < 15.0 for l in lines)
            over_budget = (o.amount_untaxed or 0.0) > 500000.0
            if any_line_under_15 or over_budget:
                o.approval_required_level = 'n2'
            else:
                o.approval_required_level = 'n1'

    def _open_min_buy_wizard(self, errors_text):
        self.ensure_one()
        wiz = self.env['sale.min.buy.wizard'].create({
            'sale_id': self.id,
            'errors_text': errors_text,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _("Validation Min Buy"),
            'res_model': 'sale.min.buy.wizard',
            'view_mode': 'form',
            'res_id': wiz.id,
            'target': 'new',
        }
    
    
    
    def _require_group(self, xmlid):
        if not self.env.user.has_group(xmlid):
            raise UserError(_("Vous n’avez pas la permission d’effectuer cette approbation."))

    def _check_support_min_buy_or_error(self, raise_exception=True):
    
        company = self.company_id or self.env.company
        company_cur = company.currency_id

        for order in self:
            cumuls = defaultdict(float)
            for line in order.order_line:
                if not line.support_id:
                    continue
                amount_company = line.currency_id._convert(
                    line.price_subtotal, company_cur, order.company_id,
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
                if raise_exception:
                    raise UserError("Minimum de commande par support non atteint :\n" + "\n".join(errors))
                return errors

        return []

    
    def _confirmation_error_message(self):
        self.ensure_one()
        if self.state not in {'draft', 'sent','to_validate','to_confirm'}:
            return _("Certaines commandes ne sont pas dans un état nécessitant une confirmation.")
        if any(
            not line.display_type
            and not line.product_template_id
            for line in self.order_line
        ):
            return _("Une ligne sur ces commandes manque un produit, vous ne pouvez pas le confirmer.")

        return False

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
            po = PurchaseOrder.with_company(self.company_id).create({
                "partner_id": vendor.id,
                "company_id": self.company_id.id,
                "origin": self.name,
                "sale_id": self.id,
            })
            for so_line, seller in pairs:
                po_uom = (seller and seller.product_uom_id) or so_line.product_id.uom_po_id or so_line.product_uom_id
                qty = so_line.product_uom_id._compute_quantity(so_line.product_uom_qty, po_uom)

                taxes = so_line.product_id.supplier_taxes_id.filtered(lambda t: t.company_id == po.company_id)
                date_planned = fields.Datetime.now()

                PurchaseOrderLine.create({
                    "order_id": po.id,
                    "product_id": so_line.product_id.id,
                    "support_id": so_line.support_id.id,
                    "name": so_line.name or so_line.product_id.display_name,
                    "product_qty": qty,
                    "product_uom_id": po_uom.id,
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
            uom_id=line.product_uom_id,
        )
        if not vendor:
            vendor = seller.partner_id if seller else False
        return vendor, seller
    
    @api.constrains('state', 'opportunity_id')
    def _check_single_validated_quote_per_opportunity(self):
        for order in self:
            if order.state == 'sale' and order.opportunity_id:
                confirmed_orders = self.env['sale.order'].search_count([
                    ('id', '!=', order.id),
                    ('opportunity_id', '=', order.opportunity_id.id),
                    ('state', '=', 'sale')
                ])
                if confirmed_orders:
                    raise ValidationError(_(
                        "Impossible de valider ce devis : "
                        "l'opportunité '%s' possède déjà un devis validé."
                    ) % order.opportunity_id.display_name)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    support_id = fields.Many2one('vendor.support',string='Support',help="Support available for the selected product.")
    commission_pct = fields.Float('Commission',compute='_compute_commission_pct',store=True,)
    public_price = fields.Float(
    related='product_id.product_tmpl_id.public_price',
    string="Prix public",
    store=False, readonly=True
    )
    is_free_line = fields.Boolean(
        string="Free Line",
        help="Line automatically created as a free discount (FOC).",
        default=False,
        index=True,
    )
    support_bonus_of_id = fields.Many2one(
        'sale.order.line',
        string="Bonus Of",
        help="If set, this line is the free bonus of the referenced paid line.",
        ondelete='cascade',
        index=True,
    )
    allowed_product_ids = fields.Many2many(
        'product.product', compute='_compute_allowed_products', store=False)
    allowed_product_tmpl_ids = fields.Many2many(
        'product.template', compute='_compute_allowed_products', store=False)

    @api.depends('support_id')
    def _compute_allowed_products(self):
        ProductT = self.env['product.template']
        ProductP = self.env['product.product']

        for line in self:
            if line.support_id:
                # with support -> only products linked to that support
                tmpl_ids = ProductT.search([
                    ('seller_ids.support_id', '=', line.support_id.id)
                ]).ids
            else:
                # no support -> all products except kind 'external'
                tmpl_ids = ProductT.search([
                    ('product_kind', '!=', 'external')
                ]).ids

            # set computed lists
            line.allowed_product_tmpl_ids = [(6, 0, tmpl_ids)]
            prod_ids = ProductP.search([('product_tmpl_id', 'in', tmpl_ids)]).ids
            line.allowed_product_ids = [(6, 0, prod_ids)]

            if line.product_id and line.product_id.id not in prod_ids:
                line.product_id = False
            if hasattr(line, 'product_template_id') and line.product_template_id and \
               line.product_template_id.id not in tmpl_ids:
                line.product_template_id = False

    def _ensure_slot_after_line(self):
        """
        Make sure there is a free sequence slot right after `self.sequence`.
        Bumps later lines by +1 so we can insert at self.sequence + 1.
        """
        self.ensure_one()
        order = self.order_id
        base = int(self.sequence or 0)

        # Lines to shift: any non-display line with sequence >= base+1 (except our own free line)
        lines_to_shift = order.order_line.filtered(
            lambda l: not l.display_type and not l.is_free_line and l.id != self.id and int(l.sequence or 0) >= base + 1
        )
        if lines_to_shift:
            # Shift in one write for performance
            for l in lines_to_shift:
                l.sequence = int(l.sequence or 0) + 1

    @api.onchange('product_id', 'product_uom_qty', 'support_id')
    def _onchange_support_free_services(self):
        if self.env.context.get('no_free_goods'):
            return
        for line in self:
            if line.display_type or line.is_free_line:
                continue

            if line.support_id and line.support_id.blacklisted:
                msg = _("Le support '%s' est blacklisté et ne peut pas être utilisé.") % line.support_id.display_name
                line.support_id = False
                return {'warning': {'title': _("Support blacklisté"), 'message': msg}}

            if line.product_id:
                product = line.product_id
                today = fields.Date.today()
                valid_from = getattr(product, 'valid_from', False)
                valid_to = getattr(product, 'valid_to', False)

                if (valid_from and today < valid_from) or (valid_to and today > valid_to):
                    msg = _("Le produit '%s' n'est pas valide à la date du %s.\nPériode de validité : %s → %s") % (
                        product.display_name,
                        today.strftime('%d/%m/%Y'),
                        valid_from.strftime('%d/%m/%Y') if valid_from else '-',
                        valid_to.strftime('%d/%m/%Y') if valid_to else '-'
                    )
                    line.product_id = False
                    return {'warning': {'title': _("Produit non valide"), 'message': msg}}

            line._apply_or_cleanup_free_services_from_support()


    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        ctx = dict(self.env.context, no_free_goods=True)
        for line in lines.with_context(ctx):
            if not line.display_type and not line.is_free_line:
                line._apply_or_cleanup_free_services_from_support()
        return lines

    def write(self, vals):
        res = super().write(vals)
        watch = {'product_id', 'product_uom_qty', 'support_id', 'is_free_line'}
        if watch.intersection(vals.keys()):
            ctx = dict(self.env.context, no_free_goods=True)
            for line in self.with_context(ctx):
                if not line.display_type and not line.is_free_line:
                    line._apply_or_cleanup_free_services_from_support()
        return res
    

    def _apply_or_cleanup_free_services_from_support(self):
        """Create/update/remove the paired free service line for this paid line based on support tiers."""
        self.ensure_one()
        support = self.support_id
        if not support:
            self._remove_existing_free_line()
            return

        free_qty, free_product = self._compute_free_qty_from_tiers(support)
        if free_qty <= 0:
            self._remove_existing_free_line()
            return

        free_line = self._get_existing_free_line()
        values = self._prepare_free_line_vals(free_product, free_qty)

        if free_line:
            update_vals = {}

            if free_line.product_id.id != values['product_id']:
                update_vals['product_id'] = values['product_id']
                update_vals['product_uom_id'] = values['product_uom_id']
                update_vals['name'] = values['name']

            # qty change
            if float(free_line.product_uom_qty) != float(values['product_uom_qty']):
                update_vals['product_uom_qty'] = values['product_uom_qty']
            
            desired_seq = int(self.sequence or 0) + 1
            if int(free_line.sequence or 0) != desired_seq:
                # if another line already occupies desired_seq, bump a slot
                conflict = self.order_id.order_line.filtered(
                    lambda l: l.id != free_line.id and not l.display_type and int(l.sequence or 0) == desired_seq
                )
                if conflict:
                    self._ensure_slot_after_line()
                update_vals['sequence'] = desired_seq

            # always enforce free price/discount
            update_vals['price_unit'] = 0.0
            update_vals['discount'] = 0.0

            if update_vals:
                free_line.with_context(no_free_goods=True).write(update_vals)
        else:
            self._ensure_slot_after_line()
            values['sequence'] = int(self.sequence or 0) + 1
            self.with_context(no_free_goods=True).order_id.write({'order_line': [(0, 0, values)]})

    def _remove_existing_free_line(self):
        free_line = self._get_existing_free_line()
        if free_line:
            free_line.with_context(no_free_goods=True).unlink()

    def _get_existing_free_line(self):
        self.ensure_one()
        return self.order_id.order_line.filtered(
            lambda l: l.is_free_line and l.support_bonus_of_id.id == self.id
        )[:1]

    def _prepare_free_line_vals(self, product, qty):
        """Prepare vals for the free service line, mirroring taxes/UoM and analytics."""
        self.ensure_one()
        order = self.order_id

        fpos = order.fiscal_position_id
        taxes = product.taxes_id.filtered(lambda t: t.company_id == order.company_id)
        taxes = fpos.map_tax(taxes) if fpos else taxes

        # Descriptive name
        name = "%s\n(%s)" % (
            product.get_product_multiline_description_sale() or product.display_name,
            _("Gratuité")
        )

        vals = {
            'order_id': order.id,
            'is_free_line': True,
            'support_bonus_of_id': self.id,
            'product_id': product.id,
            'name': name,
            'product_uom_qty': qty,
            'product_uom_id': product.uom_id.id,
            'public_price': 0.0,
            'price_unit': 0.0,
            'purchase_price': 0.0,
            'discount': 0.0,
        }

        return vals

    def _compute_free_qty_from_tiers(self, support):
        self.ensure_one()

        tier_lines = getattr(support, 'free_tier_ids', [])
        free_product = getattr(support, 'free_product_id', None) or self.product_id

        ordered = self.product_uom_qty or 0.0
        if not tier_lines or ordered <= 0:
            return 0.0, free_product

        best_min, best_percent = -1.0, 0.0
        for t in tier_lines:
            min_qty = getattr(t, 'min_qty', 0.0) or 0.0
            percent = getattr(t, 'free_percent', 0.0) or 0.0
            if min_qty <= ordered and min_qty >= best_min and percent > 0.0:
                best_min, best_percent = float(min_qty), float(percent)

        if best_percent <= 0.0:
            return 0.0, free_product

        # Free qty rounded with UoM precision
        uom = self.product_uom_id or self.product_id.uom_id
        rounding = uom.rounding or 0.01
        free_qty = float_round(ordered * (best_percent / 100.0),
                               precision_rounding=rounding)
        return (free_qty if free_qty > 0 else 0.0), free_product

    @api.depends('price_unit','purchase_price','support_id.commission_pct')
    def _compute_commission_pct(self):

        for line in self:
            fallback = float(line.support_id.commission_pct or 0.0)

            price = float(line.price_unit or 0.0)
            cost_company = float(line.purchase_price or 0.0)
            if price <= 0:
                line.commission_pct = fallback
                continue

            pct = (price - line.purchase_price) / price * 100.0 if price > 0 else 0.0

            line.commission_pct = round(pct, 2) if (cost_company > 0.0) else fallback


    @api.depends('product_template_id', 'company_id', 'currency_id', 'product_uom_id')
    def _compute_purchase_price(self):
        for line in self:
            if not line.product_template_id:
                line.purchase_price = 0.0
                continue
            line = line.with_company(line.company_id)

            product_cost = line.product_template_id.uom_id._compute_price(
                line.product_template_id.standard_price,
                line.product_uom_id,
            )

            line.purchase_price = line._convert_to_sol_currency(
                product_cost,
                line.product_template_id.cost_currency_id)
            
        