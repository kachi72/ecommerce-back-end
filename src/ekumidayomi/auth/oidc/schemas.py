"""Safe OIDC API response contracts."""

from pydantic import BaseModel, ConfigDict

from ekumidayomi.auth.oidc.settings import ProviderName


class ExternalIdentityView(BaseModel):
    """Expose a linked provider without its subject or provider claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
