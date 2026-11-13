import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional
from logging import getLogger

logger = getLogger(__name__)

class EmailService:
    def __init__(
        self,
        host: str,
        port: int,
        user: Optional[str],
        password: Optional[str],
        use_tls: bool,
        email_from: str,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.use_tls = use_tls
        self.email_from = email_from

    def send_verification_email(self, to_email: str, token: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Discord verification code"
        message["From"] = self.email_from
        message["To"] = to_email
        message.set_content(
            "Your verification code is: {token}\n\n"
            "If you did not request this, please ignore this email."
            .format(token=token)
        )
        logger.debug("Sending verification email to %s via %s:%s", to_email, self.host, self.port)
        context = ssl.create_default_context()
        with smtplib.SMTP(self.host, self.port, timeout=15) as server:
            if self.use_tls:
                server.starttls(context=context)
            if self.user and self.password:
                server.login(self.user, self.password)
            server.send_message(message)
