# -*- encoding: utf-8 -*-

from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseNotFound, HttpResponse, HttpResponseNotAllowed
from django.core.urlresolvers import reverse
from django.utils.functional import Promise
from django.db import models
from django.db.models.query import QuerySet
import json
from django.utils.safestring import SafeString

class JsonEncoderS(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Promise):
            return unicode(obj)
        elif isinstance(obj, QuerySet):
            return list(obj)
        return super(JsonEncoderS, self).default(obj)

# ----------- Filters ----------------

class CJFilter(object):
    """Base for some search criterion, represents a search field
    """
    title = ''
    _instances = []
    sequence = 10

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        CJFilter._instances.append(self)

    def real_init(self):
        pass

    def getGrammar(self):
        return {'name': self.title, 'sequence': self.sequence }

    def getQuery(self, name, domain):
        """Constructs a Django Q object, according to `domain` (as from client)

            @param name field name
        """
        raise NotImplementedError

    def to_main_report(self, idn):
        ret = {'id': idn, 'name': self.title, 'sequence': self.sequence }
        if getattr(self, 'famfam_icon', None):
            ret['famfam'] = 'famfam-' + self.famfam_icon

        return ret

    def getResults(self, request, **kwargs):
        raise NotImplementedError(self.__class__.__name__)

class CJFilter_Model(CJFilter):
    """ Search for records of some Model
    
        The `model` is a reference to some django model, like `<app>.<Model>`,
        same syntax as ForeignKey resolver.

        This one contains `fields`, a dictionary of sub-filters,
        per model field.
    """
    def __init__(self, model, **kwargs):
        self._model = model
        self._model_inst = None
        self.fields = kwargs.pop('fields', {})
        super(CJFilter_Model, self).__init__(**kwargs)

    def real_init(self):
        """Lazy initialization of filter parameters, will look into Model
        
            This cannot be done during `__init__()` because it would access
            some other Django models, propably not loaded yet, while this
            application is instantiated
        """
        if not self._model_inst:
            app, name = self._model.split('.', 1)
            self._model_inst = models.get_model(app, name)
        if not self.title:
            self.title = self._model_inst._meta.verbose_name_plural

    def getGrammar(self):
        ret = super(CJFilter_Model, self).getGrammar()
        ret['widget'] = 'model'
        ret['fields'] = {}
        for k, field in self.fields.items():
            ret['fields'][k] = field.getGrammar()
        return ret

    def getResults(self, request, domain, fields=False, group_by=False, **kwargs):
        objects = self._model_inst.objects
        if getattr(objects, 'by_request'):
            objects = objects.by_request(request)

        if domain:
            if isinstance(domain, list) and domain[0] == 'in':
                flt = self._calc_domain(domain[1])
                if flt:
                    assert isinstance(flt, models.Q), "bad result from _calc_domain(): %r" % flt
                    objects = objects.filter(flt)
            else:
                raise ValueError("Domain must be like: [in, [...]]")
        if fields:
            pass # TODO convert fields to django-like exprs
        else:  # not fields
            fields = self.fields.keys()
            fields.sort(key=lambda f: self.fields[f].sequence)
        return objects.values('id', *fields)

    def _calc_domain(self, domain):
        """ Parse a _list_ of domain expressions into a Query filter
        """
        ret = []
        op_stack = []
        for d in domain:
            if d in ('!', '|', '&'):
                op_stack.append(d)
                continue
            if isinstance(d, (tuple, list)) and len(d) == 3:
                field = self.fields[d[0]] # KeyError means we're asking for wrong field!
                ff = field.getQuery(d[0], d)
                if isinstance(ff, models.Q):
                    pass
                elif isinstance(ff, dict):
                    ff = models.Q(**ff)
                else:
                    raise TypeError("Bad query: %r" % ff)

                ret.append(ff)
            else:
                raise ValueError("Invalid domain expression: %r" % d)
            while len(op_stack) and len(ret):
                if op_stack[-1] == '!':
                    r = ret.pop()
                    ret.append(~r)
                    op_stack.pop()
                    continue
                if len(ret) < 2:
                    break
                op = op_stack.pop()
                b = ret.pop()
                a = ret.pop()
                if op == '&':
                    ret.append(a & b)
                elif op == '|':
                    ret.append(a | b)
                else:
                    raise RuntimeError("Invalid operator %r in op_stack" % op_stack[-1])
        if len(op_stack):
            raise RuntimeError("Remaining operators: %r in op_stack" % op_stack)
        if not ret:
            return models.Q()
        while len(ret) > 1:
            b = ret.pop()
            a = ret.pop()
            ret.append(a & b)

        return ret[0]

class CJFilter_Product(CJFilter_Model):

    def getGrammar(self):
        ret = super(CJFilter_Product, self).getGrammar()
        ret['widget'] = 'model-product'
        return ret

class CJFilter_String(CJFilter):
    sequence = 9

    def getGrammar(self):
        ret = super(CJFilter_String, self).getGrammar()
        ret['widget'] = 'char'
        return ret

    def getQuery(self, name, domain):
        if isinstance(domain, (list, tuple)) and len(domain) == 3:
            if domain[1] == '=':
                return { domain[0]: domain[2] }
            elif domain[1] in ('contains', 'icontains'):
                return {domain[0]+'__' + domain[1]: domain[2]}
        raise TypeError("Bad domain: %r", domain)

class CJFilter_lookup(CJFilter_Model):
    """Select *one* of some related model, with an autocomplete field
    """

    def __init__(self, model, lookup, **kwargs):
        self.lookup = lookup
        self.fields = {}
        super(CJFilter_lookup, self).__init__(model, **kwargs)

    def getGrammar(self):
        ret = super(CJFilter_lookup, self).getGrammar()
        del ret['fields']
        ret['widget'] = 'lookup'
        ret['lookup'] = reverse('ajax_lookup', args=[self.lookup,])
        return ret

class CJFilter_contains(CJFilter):
    """ Filter for an array that must contain *all of* the specified criteria

        "sub" is the filter for each of the criteria, but will be repeated N times
        and request to satisfy all of those N contents.
    """
    def __init__(self, sub_filter, **kwargs):
        assert isinstance(sub_filter, CJFilter), repr(sub_filter)
        self.sub = sub_filter
        super(CJFilter_contains, self).__init__(**kwargs)

    def getGrammar(self):
        ret = super(CJFilter_contains, self).getGrammar()
        ret['widget'] = 'contains'
        ret['sub'] = self.sub.getGrammar()
        return ret

class CJFilter_attribs(CJFilter_Model):
    #def __init__(self, sub_filter, **kwargs):
    #    assert isinstance(sub_filter, CJFilter), repr(sub_filter)
    #    self.sub = sub_filter
    #    super(CJFilter_contains, self).__init__(**kwargs)

    def getGrammar(self):
        ret = super(CJFilter_attribs, self).getGrammar()
        ret['widget'] = 'attribs'
        # ret['sub'] = self.sub.getGrammar()
        return ret


location_filter = CJFilter_Model('common.Location')
manuf_filter = CJFilter_lookup('products.Manufacturer', 'manufacturer')

product_filter = CJFilter_Product('products.ItemTemplate',
    sequence=20,
    fields = {
            'description': CJFilter_String(title=_('name'), sequence=1),
            'category': CJFilter_lookup('products.ItemCategory', 'categories', sequence=5),
            'manufacturer': manuf_filter,
            'attributes': CJFilter_attribs('products.ItemTemplateAttributes', sequence=15),
            }
    )

item_templ_c_filter = CJFilter_Model('assets.Item', title=_('asset'),
    fields = {
        'item_template': product_filter,
        },
    famfam_icon = 'computer',
    )

item_templ_filter = CJFilter_Model('assets.Item', title=_('asset'),
    fields = {
            'location': location_filter,
            'item_template': product_filter,
            'itemgroup': CJFilter_contains(item_templ_c_filter, title=_('containing'), sequence=25),
            },
    famfam_icon = 'computer',
    )

# ---------------- Cache ---------------

_reports_cache = {}

def _reports_init_cache():
    """ Global function, fill `_reports_cache` with pre-rendered data
    """
    if _reports_cache:
        return

    for rt in CJFilter._instances:
        rt.real_init()

    # These types will be used as top-level reports:
    _reports_cache['main_types'] = {
            'items': item_templ_filter,
            'products': product_filter,
            }

    _reports_cache['available_types'] = [ rt.to_main_report(k) for k, rt in _reports_cache['main_types'].items()]

# ------------------ Views -------------

def reports_app_view(request, object_id=None):
    _reports_init_cache()
    return render(request, 'reports_app.html',
            {'available_types': SafeString(json.dumps(_reports_cache['available_types'], cls=JsonEncoderS)),
            })

def reports_parts_params_view(request, part_id):
    _reports_init_cache()
    if part_id not in _reports_cache['main_types']:
        return HttpResponseNotFound("Part for type %s not found" % part_id)
    
    return render(request, 'params-%s.html' % part_id, {})

def reports_grammar_view(request, rep_type):
    _reports_init_cache()
    
    rt = _reports_cache['main_types'].get(rep_type, False)
    if not rt:
        return HttpResponseNotFound("Grammar for type %s not found" % rep_type)
    content = json.dumps(rt.getGrammar(), cls=JsonEncoderS)
    return HttpResponse(content, content_type='application/json')

def reports_cat_grammar_view(request, cat_id):
    """Return the category-specific grammar (is_bundle and attributes)
    """
    from products.models import ItemCategory
    category = get_object_or_404(ItemCategory, pk=cat_id)
    ret = {'is_bundle': category.is_bundle, 'is_group': category.is_group,
            }
    if category.is_bundle or category.is_group:
        cmc = []
        for mc in category.may_contain.all():
            cmc.append((mc.category.id, mc.category.name))
        if cmc:
            ret['may_contain'] = cmc

    ret['attributes'] = []
    for attr in category.attributes.all():
        ret['attributes'].append({'aid': attr.id, 'name': attr.name,
                'values': attr.values.values_list('id', 'value')})

    return HttpResponse(json.dumps(ret, cls=JsonEncoderS),
                        content_type='application/json')

def reports_get_preview(request, rep_type):
    """Return a subset of results, for some report
    """
    _reports_init_cache()
    
    rt = _reports_cache['main_types'].get(rep_type, False)
    if not rt:
        return HttpResponseNotFound("Report type %s not found" % rep_type)
    
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST',])

    req_data = json.loads(request.body)
    assert (req_data['model'] == rep_type), "invalid model: %r" % req_data['model']
    res = rt.getResults(request, **req_data)
    if isinstance(res, QuerySet):
        res = res[:10]
    content = json.dumps(res, cls=JsonEncoderS)
    return HttpResponse(content, content_type='application/json')

# eof