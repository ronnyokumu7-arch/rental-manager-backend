from locust import HttpUser, task, between

TEST_AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1IiwiaWF0IjoxNzg1MDA3NDA4LCJleHAiOjE3ODUwMTEwMDgsInRlbmFudF9pZCI6MSwicm9sZSI6InRlbmFudF9hZG1pbiJ9.d6CH2ItiB12C-Hmm0UFAy73PCdYMLg_cPSTis1ZtDYc"

class RentalPlatformUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.client.headers.update({
            "Authorization": TEST_AUTH_TOKEN,
            "Content-Type": "application/json"
        })

    @task(1)
    def get_invoices(self):
        """Test the invoices endpoint we just fixed."""
        self.client.get("/api/v1/invoices/", name="GET /invoices")
