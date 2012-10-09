# -*- encoding: utf-8 -*-
from django.db import models
from django.utils.translation import ugettext_lazy as _

from common.models import Supplier, Location
from assets.models import Item, ItemTemplate

from dynamic_search.api import register


"""
TODO: PR Change Order model ?
"""


class PurchaseRequestStatus(models.Model):
    name = models.CharField(verbose_name=_(u'name'), max_length=32)

    class Meta:
        verbose_name = _(u'purchase request status')
        verbose_name_plural = _(u'purchase request status')

    def __unicode__(self):
        return self.name

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_request_state_list', [])


class PurchaseRequest(models.Model):
    user_id = models.CharField(max_length=32, null=True, blank=True, verbose_name=_(u'user defined id'))
    issue_date = models.DateField(auto_now_add=True, verbose_name=_(u'issue date'))
    required_date = models.DateField(null=True, blank=True, verbose_name=_(u'date required'))
    budget = models.PositiveIntegerField(null=True, blank=True, verbose_name=_(u'budget'))
    active = models.BooleanField(default=True, verbose_name=_(u'active'))
    status = models.ForeignKey(PurchaseRequestStatus, null=True, blank=True, verbose_name=_(u'status'))
    originator = models.CharField(max_length=64, null=True, blank=True, verbose_name=_(u'originator'))
    notes = models.TextField(null=True, blank=True, verbose_name=_(u'notes'))

    #account number

    class Meta:
        verbose_name = _(u'purchase request')
        verbose_name_plural = _(u'purchase requests')

    def __unicode__(self):
        return '#%s (%s)' % (self.user_id if self.user_id else self.id, self.issue_date)

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_request_view', [str(self.id)])


class PurchaseRequestItem(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, verbose_name=_(u'purchase request'))
    item_template = models.ForeignKey(ItemTemplate, verbose_name=_(u'item template'))
    qty = models.PositiveIntegerField(verbose_name=_(u'quantity'))
    notes = models.TextField(null=True, blank=True, verbose_name=_(u'notes'))

    class Meta:
        verbose_name = _(u'purchase request item')
        verbose_name_plural = _(u'purchase request items')

    def __unicode__(self):
        return unicode(self.item_template)

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_request_view', [str(self.purchase_request.id)])


class PurchaseOrderStatus(models.Model):
    name = models.CharField(verbose_name=_(u'name'), max_length=32)

    class Meta:
        verbose_name = _(u'purchase order status')
        verbose_name_plural = _(u'purchase order status')

    def __unicode__(self):
        return self.name

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_order_state_list', [])


class PurchaseOrder(models.Model):
    user_id = models.CharField(max_length=32, null=True, blank=True, verbose_name=_(u'user defined id'))
    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, verbose_name=_(u'purchase request'))
    supplier = models.ForeignKey(Supplier, verbose_name=_(u'supplier'))
    issue_date = models.DateField(auto_now_add=True, verbose_name=_(u'issue date'))
    required_date = models.DateField(null=True, blank=True, verbose_name=_(u'date required'))
    active = models.BooleanField(default=True, verbose_name=_(u'active'))
    notes = models.TextField(null=True, blank=True, verbose_name=_(u'notes'))
    status = models.ForeignKey(PurchaseOrderStatus, null=True, blank=True, verbose_name=_(u'status'))

    class Meta:
        verbose_name = _(u'purchase order')
        verbose_name_plural = _(u'purchase orders')

    def __unicode__(self):
        return '#%s (%s)' % (self.user_id if self.user_id else self.id, self.issue_date)

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_order_view', [str(self.id)])

    def fmt_active(self):
        if self.active:
            return _(u'Open')
        else:
            return _(u'Closed')


class PurchaseOrderItemStatus(models.Model):
    name = models.CharField(verbose_name=_(u'name'), max_length=32)

    class Meta:
        verbose_name = _(u'purchase order item status')
        verbose_name_plural = _(u'purchase order item status')

    def __unicode__(self):
        return self.name

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_order_item_state_list', [])


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, verbose_name=_(u'purchase order'), related_name='items')
    item_template = models.ForeignKey(ItemTemplate, verbose_name=_(u'item template'))
    status = models.ForeignKey(PurchaseRequestStatus, null=True, blank=True, verbose_name=_(u'status'))
    agreed_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True, verbose_name=_(u'agreed price'))
    active = models.BooleanField(default=True, verbose_name=_(u'active'))
    status = models.ForeignKey(PurchaseOrderItemStatus, null=True, blank=True, verbose_name=_(u'status'))
    qty = models.PositiveIntegerField(verbose_name=_(u'quantity'))
    received_qty = models.PositiveIntegerField(default=0, null=True, blank=True, verbose_name=_(u'received'))

    class Meta:
        verbose_name = _(u'purchase order item')
        verbose_name_plural = _(u'purchase order items')

    def __unicode__(self):
        return unicode(self.item_template)

    @models.permalink
    def get_absolute_url(self):
        return ('purchase_order_view', [str(self.purchase_order.id)])

    def fmt_agreed_price(self):
        if self.agreed_price:
            return '€ %s' % self.agreed_price
        else:
            return ''

    def fmt_active(self):
        if self.active:
            return _(u'Open')
        else:
            return _(u'Closed')

class Movement(models.Model):
    date_act = models.DateField(auto_now_add=False, verbose_name=_(u'date performed'))
    date_val = models.DateField(verbose_name=_(u'date validated'), blank=True, null=True)
    create_user = models.ForeignKey('auth.User', related_name='+')
    validate_user = models.ForeignKey('auth.User', blank=True, null=True, related_name='+')
    
    name = models.CharField(max_length=32, blank=True, verbose_name=_(u'reference'))
    state = models.CharField(max_length=16, choices=[('draft', 'Draft'), ('done', 'Done')])
    stype = models.CharField(max_length=16, choices=[('in', 'Incoming'),('out',' Outgoing'), 
                ('internal', 'Internal'), ('other', 'Other')], verbose_name=_('type'))
    origin = models.CharField(max_length=64, blank=True, verbose_name=_('origin'))
    note = models.TextField(verbose_name=_('Notes'), blank=True)
    location_src = models.ForeignKey(Location, related_name='location_src')
    location_dest = models.ForeignKey(Location, related_name='location_dest')
    items = models.ManyToManyField(Item, verbose_name=_('items'), related_name='items')
        # limit_choices_to
    # todo: links with purchase or so..

    def do_close(self):
        """Closes the movement and updates the assets counters
        """
        pass

#class MovementLine(models.Model):
    #movement = models.ForeignKey(Movement)
    #asset = models.ForeignKey(Item)

register(PurchaseRequestStatus, _(u'purchase request status'), ['name'])
register(PurchaseRequest, _(u'purchase request'), ['user_id', 'id', 'budget', 'required_date', 'status__name', 'originator'])
register(PurchaseRequestItem, _(u'purchase request item'), ['item_template__description', 'qty', 'notes'])
register(PurchaseOrderStatus, _(u'purchase order status'), ['name'])
register(PurchaseOrderItemStatus, _(u'purchase order item status'), ['name'])
register(PurchaseOrder, _(u'purchase order'), ['user_id', 'id', 'required_date', 'status__name', 'supplier__name', 'notes'])
register(PurchaseOrderItem, _(u'purchase order item'), ['item_template__description', 'qty'])
