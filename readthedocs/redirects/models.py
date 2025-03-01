"""Django models for the redirects app."""

import re

import structlog
from django.db import models
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from readthedocs.core.resolver import resolve_path
from readthedocs.projects.models import Project

from .querysets import RedirectQuerySet

log = structlog.get_logger(__name__)

HTTP_STATUS_CHOICES = (
    (301, _("301 - Permanent Redirect")),
    (302, _("302 - Temporary Redirect")),
)

STATUS_CHOICES = (
    (True, _("Active")),
    (False, _("Inactive")),
)

TYPE_CHOICES = (
    ("prefix", _("Prefix Redirect")),
    ("page", _("Page Redirect")),
    ("exact", _("Exact Redirect")),
    ("sphinx_html", _("Sphinx HTMLDir -> HTML")),
    ("sphinx_htmldir", _("Sphinx HTML -> HTMLDir")),
    # ('advanced', _('Advanced')),
)

# FIXME: this help_text message should be dynamic since "Absolute path" doesn't
# make sense for "Prefix Redirects" since the from URL is considered after the
# ``/$lang/$version/`` part. Also, there is a feature for the "Exact
# Redirects" that should be mentioned here: the usage of ``$rest``
from_url_helptext = _(
    "Absolute path, excluding the domain. "
    "Example: <b>/docs/</b>  or <b>/install.html</b>",
)
to_url_helptext = _(
    "Absolute or relative URL. Example: <b>/tutorial/install.html</b>",
)
redirect_type_helptext = _("The type of redirect you wish to use.")


class Redirect(models.Model):

    """A HTTP redirect associated with a Project."""

    project = models.ForeignKey(
        Project,
        verbose_name=_("Project"),
        related_name="redirects",
        on_delete=models.CASCADE,
    )

    redirect_type = models.CharField(
        _("Redirect Type"),
        max_length=255,
        choices=TYPE_CHOICES,
        help_text=redirect_type_helptext,
    )

    from_url = models.CharField(
        _("From URL"),
        max_length=255,
        db_index=True,
        help_text=from_url_helptext,
        blank=True,
    )

    # We are denormalizing the database here to easily query for Exact Redirects
    # with ``$rest`` on them from El Proxito
    from_url_without_rest = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Only for internal querying use",
        blank=True,
        null=True,
    )

    to_url = models.CharField(
        _("To URL"),
        max_length=255,
        db_index=True,
        help_text=to_url_helptext,
        blank=True,
    )
    force = models.BooleanField(
        _("Force redirect"),
        null=True,
        default=False,
        help_text=_("Apply the redirect even if the page exists."),
    )

    http_status = models.SmallIntegerField(
        _("HTTP Status"),
        choices=HTTP_STATUS_CHOICES,
        default=302,
    )
    status = models.BooleanField(choices=STATUS_CHOICES, default=True)

    create_dt = models.DateTimeField(auto_now_add=True)
    update_dt = models.DateTimeField(auto_now=True)

    objects = RedirectQuerySet.as_manager()

    class Meta:
        verbose_name = _("redirect")
        verbose_name_plural = _("redirects")
        ordering = ("-update_dt",)

    def save(self, *args, **kwargs):
        if self.redirect_type == "exact" and "$rest" in self.from_url:
            self.from_url_without_rest = self.from_url.replace("$rest", "")
        super().save(*args, **kwargs)

    def __str__(self):
        redirect_text = "{type}: {from_to_url}"
        if self.redirect_type in ["prefix", "page", "exact"]:
            return redirect_text.format(
                type=self.get_redirect_type_display(),
                from_to_url=self.get_from_to_url_display(),
            )
        return gettext(
            "Redirect: {}".format(
                self.get_redirect_type_display(),
            ),
        )

    def get_from_to_url_display(self):
        if self.redirect_type in ["prefix", "page", "exact"]:
            from_url = self.from_url
            to_url = self.to_url
            if self.redirect_type == "prefix":
                to_url = "/{lang}/{version}/".format(
                    lang=self.project.language,
                    version=self.project.default_version,
                )
            return "{from_url} -> {to_url}".format(
                from_url=from_url,
                to_url=to_url,
            )
        return ""

    def get_full_path(
        self, filename, language=None, version_slug=None, allow_crossdomain=False
    ):
        """
        Return a full path for a given filename.

        This will include version and language information. No protocol/domain
        is returned.
        """
        # Handle explicit http redirects
        if allow_crossdomain and re.match("^https?://", filename):
            return filename

        return resolve_path(
            project=self.project,
            language=language,
            version_slug=version_slug,
            filename=filename,
        )

    def get_redirect_path(self, path, full_path=None, language=None, version_slug=None):
        method = getattr(
            self,
            "redirect_{type}".format(
                type=self.redirect_type,
            ),
        )
        return method(
            path, full_path=full_path, language=language, version_slug=version_slug
        )

    def redirect_prefix(self, path, full_path, language=None, version_slug=None):
        if path.startswith(self.from_url):
            log.debug("Redirecting...", redirect=self)
            # pep8 and blank don't agree on having a space before :.
            cut_path = path[len(self.from_url) :]  # noqa

            to = self.get_full_path(
                filename=cut_path,
                language=language,
                version_slug=version_slug,
                allow_crossdomain=False,
            )
            return to

    def redirect_page(self, path, full_path, language=None, version_slug=None):
        if path == self.from_url:
            log.debug("Redirecting...", redirect=self)
            to = self.get_full_path(
                filename=self.to_url.lstrip("/"),
                language=language,
                version_slug=version_slug,
                allow_crossdomain=True,
            )
            return to

    def redirect_exact(self, path, full_path, language=None, version_slug=None):
        if full_path == self.from_url:
            log.debug("Redirecting...", redirect=self)
            return self.to_url
        # Handle full sub-level redirects
        if "$rest" in self.from_url:
            match = self.from_url.split("$rest", maxsplit=1)[0]
            if full_path.startswith(match):
                cut_path = full_path.replace(match, self.to_url, 1)
                return cut_path

    def redirect_sphinx_html(self, path, full_path, language=None, version_slug=None):
        for ending in ["/", "/index.html"]:
            if path.endswith(ending):
                log.debug("Redirecting...", redirect=self)
                path = path[1:]  # Strip leading slash.
                to = re.sub(ending + "$", ".html", path)
                return self.get_full_path(
                    filename=to,
                    language=language,
                    version_slug=version_slug,
                    allow_crossdomain=False,
                )

    def redirect_sphinx_htmldir(
        self, path, full_path, language=None, version_slug=None
    ):
        if path.endswith(".html"):
            log.debug("Redirecting...", redirect=self)
            path = path[1:]  # Strip leading slash.
            to = re.sub(".html$", "/", path)
            return self.get_full_path(
                filename=to,
                language=language,
                version_slug=version_slug,
                allow_crossdomain=False,
            )
