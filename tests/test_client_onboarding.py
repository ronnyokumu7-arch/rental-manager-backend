from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.client import ClientCreate
from app.schemas.client_invite import ClientIntakeCreate
from app.schemas.vetting import VettingDrivingDetails
from app.services.client_verification import missing_client_verification_requirements


def basic_client_payload(**values):
    return {
        "first_name": "Amina",
        "last_name": "Otieno",
        "phone": "+254700000000",
        "id_number": "12345678",
        **values,
    }


def test_basic_client_can_be_created_before_driving_details_or_documents():
    client = ClientCreate(**basic_client_payload())

    assert client.driving_arrangement == "pending"
    assert client.dl_number is None
    assert client.driver is None


def test_public_intake_accepts_basic_details_without_driving_info_or_documents():
    client = ClientIntakeCreate(
        **basic_client_payload(id_type="national_id")
    )

    assert client.driving_arrangement == "pending"
    assert client.id_image_front is None
    assert client.id_image_back is None
    assert client.dl_image_front is None


@pytest.mark.parametrize(
    "values",
    [
        {"dl_number": "DL-123"},
    ],
)
def test_self_drive_requires_licence_number_and_expiry_date(values):
    with pytest.raises(ValidationError):
        ClientCreate(**basic_client_payload(driving_arrangement="self_drive", **values))


def test_self_drive_does_not_require_licence_issue_date():
    client = ClientCreate(
        **basic_client_payload(
            driving_arrangement="self_drive",
            dl_number="DL-123",
            dl_expiry=date.today() + timedelta(days=30),
        )
    )

    assert client.dl_issued_date is None


def test_self_drive_accepts_complete_licence_details():
    client = ClientCreate(
        **basic_client_payload(
            driving_arrangement="self_drive",
            dl_number="DL-123",
            dl_issued_date=date.today() - timedelta(days=30),
            dl_expiry=date.today() + timedelta(days=30),
        )
    )

    assert client.dl_issued_date == date.today() - timedelta(days=30)


@pytest.mark.parametrize(
    "driver_dates",
    [
        {"dl_issued_date": date.today() - timedelta(days=30)},
    ],
)
def test_own_driver_still_requires_licence_expiry_date(driver_dates):
    driver = {
        "full_name": "Brian Otieno",
        "phone": "+254711111111",
        "id_number": "87654321",
        "dl_number": "DL-456",
        **driver_dates,
    }

    with pytest.raises(ValidationError):
        ClientCreate(**basic_client_payload(driving_arrangement="own_driver", driver=driver))


def test_own_driver_accepts_complete_licence_details():
    client = ClientCreate(
        **basic_client_payload(
            driving_arrangement="own_driver",
            driver={
                "full_name": "Brian Otieno",
                "phone": "+254711111111",
                "id_number": "87654321",
                "dl_number": "DL-456",
                "dl_issued_date": date.today() - timedelta(days=30),
                "dl_expiry": date.today() + timedelta(days=30),
            },
        )
    )

    assert client.driver is not None
    assert client.driver.dl_issued_date == date.today() - timedelta(days=30)


def test_own_driver_does_not_require_licence_issue_date():
    client = ClientCreate(
        **basic_client_payload(
            driving_arrangement="own_driver",
            driver={
                "full_name": "Brian Otieno",
                "phone": "+254711111111",
                "id_number": "87654321",
                "dl_number": "DL-456",
                "dl_expiry": date.today() + timedelta(days=30),
            },
        )
    )

    assert client.driver is not None
    assert client.driver.dl_issued_date is None


def test_verification_does_not_require_self_drive_issue_date():
    details = VettingDrivingDetails(
        driving_arrangement="self_drive",
        dl_number="DL-123",
        dl_expiry=date.today() + timedelta(days=30),
    )

    assert details.dl_issued_date is None


def test_verification_still_requires_self_drive_licence_number_and_expiry():
    with pytest.raises(ValidationError):
        VettingDrivingDetails(
            driving_arrangement="self_drive",
            dl_number="DL-123",
        )


def test_verification_does_not_require_my_driver_issue_date():
    details = VettingDrivingDetails(
        driving_arrangement="own_driver",
        driver_full_name="Brian Otieno",
        driver_phone="+254711111111",
        driver_id_number="87654321",
        driver_dl_number="DL-456",
        driver_dl_expiry=date.today() + timedelta(days=30),
    )

    assert details.driver_dl_issued_date is None


def test_verification_still_requires_my_driver_licence_expiry():
    with pytest.raises(ValidationError):
        VettingDrivingDetails(
            driving_arrangement="own_driver",
            driver_full_name="Brian Otieno",
            driver_phone="+254711111111",
            driver_id_number="87654321",
            driver_dl_number="DL-456",
        )


@pytest.mark.parametrize(
    "driving_details",
    [
        {
            "driving_arrangement": "self_drive",
            "dl_number": "DL-123",
            "dl_expiry": date.today() + timedelta(days=30),
            "dl_issued_date": None,
            "dl_image_front": "client-dl.jpg",
        },
        {
            "driving_arrangement": "own_driver",
            "driver_full_name": "Brian Otieno",
            "driver_phone": "+254711111111",
            "driver_id_number": "87654321",
            "driver_dl_number": "DL-456",
            "driver_dl_expiry": date.today() + timedelta(days=30),
            "driver_dl_issued_date": None,
            "driver_id_image_front": "driver-id.jpg",
            "driver_dl_image_front": "driver-dl.jpg",
        },
    ],
)
def test_activation_requirements_do_not_include_licence_issue_date(driving_details):
    client = SimpleNamespace(
        verification_status="verified",
        id_image_front="client-id-front.jpg",
        id_image_back="client-id-back.jpg",
        selfie_with_id_image="selfie.jpg",
        driving_arrangement=driving_details["driving_arrangement"],
        dl_number=driving_details.get("dl_number"),
        dl_expiry=driving_details.get("dl_expiry"),
        dl_issued_date=driving_details.get("dl_issued_date"),
        dl_image_front=driving_details.get("dl_image_front"),
        driver_full_name=driving_details.get("driver_full_name"),
        driver_phone=driving_details.get("driver_phone"),
        driver_id_number=driving_details.get("driver_id_number"),
        driver_dl_number=driving_details.get("driver_dl_number"),
        driver_dl_expiry=driving_details.get("driver_dl_expiry"),
        driver_dl_issued_date=driving_details.get("driver_dl_issued_date"),
        driver_id_image_front=driving_details.get("driver_id_image_front"),
        driver_dl_image_front=driving_details.get("driver_dl_image_front"),
    )

    assert missing_client_verification_requirements(client) == {}
