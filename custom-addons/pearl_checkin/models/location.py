# -*- coding: utf-8 -*-
from odoo import fields, models


class PearlLocation(models.Model):
    _name = 'pearl.location'
    _description = 'Pearl Location / Neighbourhood'
    _order = 'name asc'

    name = fields.Char(
        string='Neighbourhood Name',
        required=True,
        translate=True,
        index='trigram',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    description = fields.Text(
        string='Description',
    )
