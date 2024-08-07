import collections

import arg
from django import http
from django import shortcuts
from django.contrib import messages
from django.core import exceptions
import django.views.generic.edit as edit_views
import formtools.wizard.views as wizard_views

import djarg.forms


class SuccessMessageMixin:
    """
    Similar to Django's SuccessMessageMixin, allows views to add
    a success message when successfully finished.

    Users can override the ``success_message`` attribute or
    override the ``get_success_message(self, args, results)`` method.
    The latter takes the arguments provided to the main view ``func``
    attribute and the results from running the view ``func``.
    """

    success_message = ''

    def get_success_message(self, args, results):
        return self.success_message.format(**{**{'results': results}, **args})

    def set_success_message(self):
        success_message = self.get_success_message(
            self.func_args, self.func_results
        )
        if success_message:
            messages.success(self.request, success_message)

    # Set the message on form_valid() (for form views) and done()
    # (for wizard views)
    def form_valid(self, form):
        response = super().form_valid(form)
        self.set_success_message()

        return response

    def done(self, *args, **kwargs):
        response = super().done(*args, **kwargs)
        self.set_success_message()

        return response


class ViewMixin:
    def get_default_args(self):
        """
        Return any arguments that should be sent to the function and
        made available during lazy form field loading.
        """
        return {'request': self.request}


class FormMixin(ViewMixin):
    func = None
    raise_run_errors = False

    def run_func(self, form):
        self.func_args = {**self.get_default_args(), **form.cleaned_data}
        self.func_results = arg.s()(self.func)(**self.func_args)
        return self.func_results

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except Exception as exc:
            if not self.raise_run_errors:
                form = self.get_form()
                form.add_error(None, exc)
                return self.form_invalid(form)
            else:
                raise

    def form_valid(self, form):
        self.run_func(form)
        return super().form_valid(form)

    def get_form(self, *args, **kwargs):
        form = super().get_form(*args, **kwargs)
        return djarg.forms.adapt(form, self.func, self.get_default_args())


class SingleObjectMixin(ViewMixin, edit_views.SingleObjectMixin):
    def get_default_args(self):
        return {**super().get_default_args(), 'object': self.object}

    def get_queryset(self):
        """
        Returns the queryset for single-object views. If the queryset as been
        overridden to be a "lazy" function (e.g. from ``python-args``), the
        function will be evaluated with ``request`` as a keyword argument and
        returned. Otherwise, it defaults to Django's generic detail-view
        ``get_queryset()`` function.
        """
        if isinstance(self.queryset, arg.Lazy):
            return arg.load(self.queryset, request=self.request)
        else:
            return super().get_queryset()

    def get(self, request, *args, **kwargs):
        self.request = request
        self.object = self.get_object()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.request = request
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)


class MultipleObjectsMixin(ViewMixin, edit_views.ContextMixin):
    """
    Similar to Django's SingleObjectMixin, but allows for pulling
    multile arguments through GET parameters.

    Most of this code was directly adapted from

    """

    model = None
    queryset = None
    context_objects_name = None
    url_query_arg = 'pk'

    def get_objects(self):
        """
        Return the objects the view is displaying.
        Require ``self.queryset`` and a ``pk`` argument in the GET query string.
        Subclasses can override this to return any object.
        """
        queryset = self.get_queryset()

        query_vals = self.request.GET.getlist(self.url_query_arg)
        queryset = queryset.filter(**{f'{self.url_query_arg}__in': query_vals})

        # Get the objects
        objects = list(queryset)
        if not objects:
            raise http.Http404(
                f'No {queryset.model._meta.verbose_name_plural} found matching'
                ' the query'
            )
        elif len(objects) != len(query_vals):
            raise http.Http404(
                f'Some {queryset.model._meta.verbose_name_plural} not found'
                ' in query.'
            )

        return objects

    def get_queryset(self):
        """
        Returns the queryset for multi-object views. If the queryset as been
        overridden to be a "lazy" function (e.g. from ``python-args``), the
        function will be evaluated with ``request`` as a keyword argument and
        returned. Otherwise, it defaults to Django's generic detail-view
        ``get_queryset()`` function.
        """
        if isinstance(self.queryset, arg.Lazy):
            return arg.load(self.queryset, request=self.request)
        else:
            return edit_views.SingleObjectMixin.get_queryset(self)

    def get_context_objects_name(self, objects):
        """Get the name to use for the object."""
        return self.context_objects_name

    def get_context_data(self, **kwargs):
        """Insert the single object into the context dict."""
        context = {}
        context['objects'] = self.objects
        context_objects_name = self.get_context_objects_name(self.objects)
        if context_objects_name:  # pragma: no cover
            context[context_objects_name] = self.objects
        context.update(kwargs)
        return super().get_context_data(**context)

    def get_default_args(self):
        return {**super().get_default_args(), 'objects': self.objects}

    def get(self, request, *args, **kwargs):
        self.request = request
        self.objects = self.get_objects()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.request = request
        self.objects = self.get_objects()
        return super().post(request, *args, **kwargs)


class FormView(FormMixin, edit_views.FormView):
    """
    A generic form view that runs a binded python-args function.

    Instatiate the ``FormView`` similar to a regular django ``FormView``,
    and also declare the ``func`` attribute to point to a ``python-args``
    function.

    The form of this view will automatically be adapted to use the
    validators of the function, and the ``form_valid`` method will
    run the function with the parameters from the form.
    """


class ObjectFormView(SingleObjectMixin, FormView):
    """
    A generic view for single objects that runs a binded python-args function.

    Similar to `FormView`, the form of this view will automatically be
    adapted to use the validators of the function, and the ``form_valid``
    method will run the function with the parameters from the form.
    """


class ObjectsFormView(MultipleObjectsMixin, FormView):
    """
    A generic view for multiple objects that runs a binded python-args function.

    Similar to `FormView`, the form of this view will automatically be
    adapted to use the validators of the function, and the ``form_valid``
    method will run the function with the parameters from the form.
    """


class WizardView(ViewMixin, wizard_views.WizardView):
    """
    Adaptation of django-formtool's wizard view.

    Children of this class, such as ``SessionWizardView``, can use
    lazy evaluation methods present in python-args.
    """

    func = None
    raise_run_errors = False

    def get_form_list(self, until=None):
        """
        This method returns a form_list based on the initial form list but
        checks if there is a condition method/value in the condition_list.
        If an entry exists in the condition list, it will call/read the value
        and respect the result. (True means add the form, False means ignore
        the form)

        The form_list is always generated on the fly because condition methods
        could use data from other (maybe previous forms).
        """
        form_list = collections.OrderedDict()
        if getattr(self, '_check_cond_started', False):
            # Guard against infinite recursion, in the case a get_form_list is
            # called in the context of a condition() call.
            for step, form_class in self.form_list.items():
                if step == until:
                    break
                form_list[step] = form_class
            return form_list

        self._check_cond_started = True

        for step, form_class in self.form_list.items():
            if step == until:
                break

            condition = self.condition_dict.get(step, True)
            if callable(condition):
                if isinstance(condition, arg.func):
                    # Evaluate the cleaned data so far. If None, it means
                    # a previous step didn't validate and we should include
                    # the form as a step until we have enough data to
                    # invalidate it
                    args_so_far = self.get_cleaned_data(*form_list)
                    if args_so_far is not None:
                        condition = arg.load(
                            condition,
                            **{**self.get_default_args(), **args_so_far},
                        )
                    else:
                        condition = True
                else:
                    condition = condition(self)

            if condition:
                form_list[step] = form_class

        del self._check_cond_started
        return form_list

    def get_form(self, step=None, **kwargs):
        """Get a form for a specific step"""
        form = super().get_form(step=step, **kwargs)
        if step is None:
            step = self.steps.current

        steps_so_far = self.get_form_list(until=step)
        if getattr(self, '_check_get_cleaned_data', False):
            # Guard against infinite recursion, in the case a get_form_list is
            # called in the context of a get_cleaned_data() in condition() call.
            args_so_far = self.get_cleaned_data(*steps_so_far) or {}
            self._check_get_cleaned_data = True
            del self._check_get_cleaned_data
        else:
            args_so_far = {}
        return djarg.forms.adapt(
            form, self.func, {**self.get_default_args(), **args_so_far}
        )

    def run_func(self):
        """
        Run the primary function. This should be called from the "done()"
        method that is overridden by users.
        """
        self.func_args = {
            **self.get_default_args(),
            **self.get_cleaned_data(*self.get_form_list()),
        }
        self.func_results = arg.s()(self.func)(**self.func_args)
        return self.func_results

    def get_success_url(self):
        if not self.success_url:  # pragma: no cover
            raise exceptions.ImproperlyConfigured(
                f'{self.__class__.__name__} does not define a success_url.'
            )

        return self.success_url

    def render_done(self, form, **kwargs):
        """
        Overrides render_done and shows a revalidation failure if
        any errors happened.
        """
        try:
            return super().render_done(form, **kwargs)
        except Exception as exc:
            if not self.raise_run_errors:
                form.add_error(None, exc)
                return self.render_revalidation_failure(
                    self.steps.current, form
                )
            else:
                raise

    def done(self, *args, **kwargs):
        self.run_func()
        return shortcuts.redirect(self.get_success_url())


class SessionWizardView(WizardView):
    """
    A WizardView with pre-configured SessionStorage backend.
    """

    storage_name = 'formtools.wizard.storage.session.SessionStorage'


class ObjectWizardView(SingleObjectMixin, WizardView):
    """
    A WizardView that operates on a single object.
    """


class SessionObjectWizardView(ObjectWizardView):
    """
    An ObjectWizardView with pre-configured SessionStorage backend.
    """

    storage_name = 'formtools.wizard.storage.session.SessionStorage'


class ObjectsWizardView(MultipleObjectsMixin, WizardView):
    """
    A WizardView that operates on multiple objects.
    """


class SessionObjectsWizardView(ObjectsWizardView):
    """
    An ObjectsWizardView with pre-configured SessionStorage backend.
    """

    storage_name = 'formtools.wizard.storage.session.SessionStorage'
