For this app, OCI authentication is standard OIDC Authorization Code flow using an OCI IAM Identity Domain.
Required OCI setup:

In OCI Console, go to your Identity Domain:
Identity & Security → Domains → select your domain.

Create a custom application:
Integrated applications → Add application → choose Confidential application.

Configure it as an OAuth/OIDC client:
Client type: Confidential
Grant type: Authorization Code
Redirect URL, exactly matching the app:https://127.0.0.1:8080/auth/callback
If you use another hostname, configure that exact URL instead.
Scopes:openid profile email


Save the generated:
Client ID
Client Secret

Activate the application.

Assign users/groups if you want to restrict who can sign in.

Then set your .env:
OCI_IAM_DOMAIN_URL=https://<your-identity-domain-url>
OCI_IAM_CLIENT_ID=<client-id>
OCI_IAM_CLIENT_SECRET=<client-secret>
OCI_IAM_REDIRECT_URI=https://127.0.0.1:8080/auth/callback
OCI_IAM_SCOPES=openid profile email
OCI_COMPANION_COOKIE_SECURE=true

Important: since https://127.0.0.1:8080 works on your desktop but localhost does not, use 127.0.0.1 consistently in both OCI and .env.
The ~/.oci config is separate: it is for scanning OCI resources after the web app starts. The IAM app above is only for browser login.
Oracle docs used: IAM identity domains overview, custom/confidential applications, and application activation docs:
https://docs.oracle.com/en-us/iaas/Content/Identity/home.htm
https://docs.oracle.com/en-us/iaas/Content/Identity/applications/add-applications.htm
https://docs.oracle.com/en-us/iaas/Content/Identity/applications/activate-applications.htm