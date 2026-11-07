"""Shared verification gate for client activation, review, and booking."""
from app.models.clients import Client, ClientVerificationStatus


def missing_client_verification_requirements(client: Client) -> dict[str, str]:
    """Return every outstanding requirement without changing client state."""
    missing: dict[str, str] = {}

    if client.verification_status != ClientVerificationStatus.verified.value:
        missing["verification_status"] = "Client verification must be approved first"
    if not client.id_image_front:
        missing["id_image_front"] = "A photo of the front of the client's ID is required"
    if not client.id_image_back:
        missing["id_image_back"] = "A photo of the back of the client's ID is required"
    if not client.selfie_with_id_image:
        missing["selfie_with_id"] = "A selfie holding the client's ID is required"

    arrangement = client.driving_arrangement or "pending"
    if arrangement == "pending":
        missing["driving_arrangement"] = "Choose a driving arrangement during verification"
    elif arrangement == "self_drive":
        if not client.dl_number:
            missing["dl_number"] = "The client's driver's licence number is required"
        if not client.dl_expiry:
            missing["dl_expiry"] = "The client's driver's licence expiry date is required"
        if not client.dl_image_front:
            missing["dl_image_front"] = "A photo of the client's driver's licence is required"
    elif arrangement == "own_driver":
        if not client.driver_full_name:
            missing["driver_full_name"] = "The personal driver's full name is required"
        if not client.driver_phone:
            missing["driver_phone"] = "The personal driver's phone number is required"
        if not client.driver_id_number:
            missing["driver_id_number"] = "The personal driver's ID number is required"
        if not client.driver_dl_number:
            missing["driver_dl_number"] = "The personal driver's licence number is required"
        if not client.driver_dl_expiry:
            missing["driver_dl_expiry"] = "The personal driver's licence expiry date is required"
        if not client.driver_id_image_front:
            missing["driver_id_image_front"] = "A photo of the personal driver's ID is required"
        if not client.driver_dl_image_front:
            missing["driver_dl_image_front"] = "A photo of the personal driver's licence is required"

    return missing
