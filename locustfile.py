from locust import HttpUser, task, between

class LearnifyUser(HttpUser):

    wait_time = between(1, 3)

    @task
    def homepage(self):
        self.client.get("/")

    @task
    def login_page(self):
        self.client.get("/login")

    @task
    def dashboard(self):
        self.client.get("/dashboard")

    @task
    def my_topics(self):
        self.client.get("/my-topics")