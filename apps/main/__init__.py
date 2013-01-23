# -*- encoding: utf-8 -*-
from django.utils.translation import ugettext_lazy as _

import assets
import inventory
import movements

from common.api import register_menu, user_is_staff

from assets.models import Item, ItemGroup, State

register_menu([
    {'text':_(u'home'), 'view':'home', 'famfam':'house', 'position':0},


    #{'text':_(u'tools'), 'view':'import_wizard', 'links': [
    #    {'text':_(u'import'), 'view':'import_wizard', 'famfam':'lightning_add'},
    #],'famfam':'wrench', 'name':'tools','position':12},

    {'text':_(u'setup'), 'view':'about', 'links': [
        assets.state_list,
        movements.purchase_request_state_list,
        movements.purchase_order_state_list,
        movements.purchase_order_item_state_list,
    ],'famfam':'cog', 'name':'setup','position':20, 
    'condition': user_is_staff
    },
])
