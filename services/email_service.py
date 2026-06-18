import ssl
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


def send_document_email(to_email, subject, body_html, pdf_bytes, filename, app_config):
    """
    Send a PDF document as an email attachment using SMTP/SSL (port 465).

    Returns (True, None) on success, (False, error_str) on failure.
    """
    mail_server   = app_config.get('MAIL_SERVER',   'smtp.gmail.com')
    mail_port     = int(app_config.get('MAIL_PORT',   465))
    mail_username = app_config.get('MAIL_USERNAME',  '')
    mail_password = app_config.get('MAIL_PASSWORD',  '')
    mail_from     = app_config.get('MAIL_FROM',      '') or mail_username

    if not mail_username or not mail_password:
        return False, 'Email not configured — set MAIL_USERNAME and MAIL_PASSWORD environment variables'

    try:
        msg = MIMEMultipart('mixed')
        msg['From']    = mail_from
        msg['To']      = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        part = MIMEBase('application', 'pdf')
        part.set_payload(pdf_bytes if isinstance(pdf_bytes, bytes) else pdf_bytes.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
        msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(mail_server, mail_port, context=context) as server:
            server.login(mail_username, mail_password)
            server.sendmail(mail_from, to_email, msg.as_string())

        return True, None

    except smtplib.SMTPAuthenticationError:
        return False, 'SMTP authentication failed — check your username and password (use an App Password for Gmail)'
    except smtplib.SMTPException as e:
        return False, f'SMTP error: {e}'
    except Exception as e:
        return False, f'Email error: {e}'
