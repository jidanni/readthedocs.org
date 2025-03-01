"""Forms for core app."""

import structlog
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout, Submit
from django import forms
from django.contrib.auth.models import User
from django.forms.fields import CharField
from django.utils.translation import gettext_lazy as _

from readthedocs.core.history import set_change_reason

from .models import UserProfile

log = structlog.get_logger(__name__)


class UserProfileForm(forms.ModelForm):
    first_name = CharField(label=_("First name"), required=False, max_length=30)
    last_name = CharField(label=_("Last name"), required=False, max_length=30)

    class Meta:
        model = UserProfile
        # Don't allow users edit someone else's user page
        profile_fields = ["first_name", "last_name", "homepage"]
        optout_email_fields = [
            "optout_email_config_file_deprecation",
            "optout_email_build_image_deprecation",
        ]
        fields = (
            *profile_fields,
            *optout_email_fields,
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
        except AttributeError:
            pass

        self.helper = FormHelper()
        field_sets = [
            Fieldset(
                _("User settings"),
                *self.Meta.profile_fields,
            ),
            Fieldset(
                _("Email settings"),
                *self.Meta.optout_email_fields,
            ),
        ]
        self.helper.layout = Layout(*field_sets)
        self.helper.add_input(Submit("save", _("Save")))

    def save(self, commit=True):
        first_name = self.cleaned_data.pop("first_name", None)
        last_name = self.cleaned_data.pop("last_name", None)
        profile = super().save(commit=commit)
        if commit:
            user = profile.user
            user.first_name = first_name
            user.last_name = last_name
            # SimpleHistoryModelForm isn't used here
            # because the model of this form is `UserProfile`, not `User`.
            set_change_reason(user, self.get_change_reason())
            user.save()
        return profile

    def get_change_reason(self):
        klass = self.__class__.__name__
        return f"origin=form class={klass}"


class UserDeleteForm(forms.ModelForm):
    username = CharField(
        label=_("Username"),
        help_text=_("Please type your username to confirm."),
    )

    class Meta:
        model = User
        fields = ["username"]

    def clean_username(self):
        data = self.cleaned_data["username"]

        if self.instance.username != data:
            raise forms.ValidationError(_("Username does not match!"))

        return data


class UserAdvertisingForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["allow_ads"]


class FacetField(forms.MultipleChoiceField):

    """
    For filtering searches on a facet.

    Has validation for the format of facet values.
    """

    def valid_value(self, value):
        """
        Although this is a choice field, no choices need to be supplied.

        Instead, we just validate that the value is in the correct format for
        facet filtering (facet_name:value)
        """
        if ":" not in value:
            return False
        return True
