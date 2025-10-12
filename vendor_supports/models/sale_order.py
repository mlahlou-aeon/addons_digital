# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError,UserError
from dateutil.relativedelta import relativedelta
from collections import defaultdict

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

    purchase_order_count = fields.Integer(
        string="Purchase Orders",
        compute="_get_po",
    )


    @api.onchange('order_line')
    def _onchange_check_support_min_buy(self):
        """Alerte à l'édition si un Minimum Buy (par support) n'est pas atteint."""
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

        # group lines by vendor (from your logic)
        grouped = {}  # {partner_id: [(line, sellerinfo or False), ...]}
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

                price = (seller and seller.price) or (so_line.product_id.standard_price or 0.0)
                seller_currency = (seller and seller.currency_id) or False
                if seller_currency and seller_currency != po.currency_id:
                    price = seller_currency._convert(price, po.currency_id, po.company_id, fields.Date.today())

                taxes = so_line.product_id.supplier_taxes_id.filtered(lambda t: t.company_id == po.company_id)
                date_planned = fields.Datetime.now()
                if seller and seller.delay:
                    date_planned += relativedelta(days=seller.delay)

                PurchaseOrderLine.create({
                    "order_id": po.id,
                    "product_id": so_line.product_id.id,
                    "support_id": so_line.support_id.id,
                    "name": so_line.name or so_line.product_id.display_name,
                    "product_qty": qty,
                    "product_uom": po_uom.id,
                    "price_unit": price,
                    "date_planned": date_planned,
                    "taxes_id": [(6, 0, taxes.ids)],
                })
            created_pos.append(po)


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
        for order in self:
            currency = order.currency_id
            discount_product = order._get_support_discount_product()

            # Lignes sources (hors lignes déjà remise)
            src_lines = order.order_line.filtered(lambda l: not l.display_type and not l.is_support_discount_line and l.support_id)

            # Grouper par support
            by_support = defaultdict(list)
            for l in src_lines:
                by_support[l.support_id].append(l)

            # Indexer les lignes de remise existantes par support
            existing = { (l.support_id.id): l for l in order.order_line.filtered(lambda l: l.is_support_discount_line) }

            # Pour chaque support : déterminer le % applicable (meilleur seuil atteint)
            supports_seen = set()
            for support, lines in by_support.items():
                supports_seen.add(support.id)

                total_qty = sum(l.product_uom_qty for l in lines)
                tiers = support.free_tier_ids.filtered(lambda t: total_qty >= (t.min_qty or 0.0))
                if tiers:
                    best = tiers.sorted(key=lambda t: t.min_qty)[-1]
                    rate = (best.free_percent or 0.0) / 100.0
                else:
                    rate = 0.0

                # Base de remise = somme HT des lignes du support
                base_taxed = sum(l.price_total for l in lines)  # déjà en devise du devis
                discount_amount = currency.round(base_taxed * rate)  # montant positif à déduire

                # Créer / mettre à jour / supprimer la ligne de remise
                disc_line = existing.get(support.id)
                if discount_amount > 0:
                    order_id = self.env['sale.order'].search([('name','=',order.name)])
                    vals = {
                        'order_id': order_id.id,
                        'product_id': discount_product.id,
                        'name': f"Remise {support.display_name} ({int(rate*100)}%)",
                        'product_uom_qty': 1.0,
                        'price_unit': -discount_amount,   # négatif = déduction
                        'tax_id': [(6, 0, [])],           # pas de taxes sur la remise globale
                        'support_id': support.id,
                        'is_support_discount_line': True,
                        'display_type': False,
                    }
                    if disc_line:
                        disc_line.with_context(skip_support_discount=True).write(vals)
                    else:
                        self.env['sale.order.line'].with_context(skip_support_discount=True).create(vals)
                else:
                    if disc_line:
                        disc_line.with_context(skip_support_discount=True).unlink()

            # Nettoyer les remises dont le support n'est plus présent
            for sup_id, line in existing.items():
                if sup_id not in supports_seen:
                    line.with_context(skip_support_discount=True).unlink()

    # --- déclencheurs : édition, création, écriture, confirmation ---
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
