from app.services.storage import _get_tenant_folder


def test_storage_folder_is_always_tenant_scoped():
    assert _get_tenant_folder(42, "compliance") == "tenant_42/compliance"
