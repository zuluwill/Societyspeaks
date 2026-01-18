"""
Slack Integration for Briefings

Sends brief runs to Slack channels via incoming webhooks.
"""

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def send_brief_to_slack(brief_run, briefing):
    """
    Send a brief run to Slack via webhook.
    
    Args:
        brief_run: BriefRun instance with items
        briefing: Briefing instance with slack_webhook_url configured
        
    Returns:
        bool: True if sent successfully, False otherwise
    """
    if not briefing.slack_webhook_url:
        logger.debug(f"No Slack webhook configured for briefing {briefing.id}")
        return False
    
    try:
        # Build Slack message blocks
        blocks = []
        
        # Header
        header_text = briefing.header_text or f"Your {briefing.name}"
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True
            }
        })
        
        # Date context
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f":newspaper: *{datetime.utcnow().strftime('%B %d, %Y')}*"
            }]
        })
        
        blocks.append({"type": "divider"})
        
        # Items
        items = brief_run.items[:10]  # Limit to 10 items for Slack
        for i, item in enumerate(items, 1):
            # Source badge
            source_text = f" _via {item.source_name}_" if item.source_name else ""
            
            # Headline
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{i}. {item.headline}*{source_text}"
                }
            })
            
            # Bullets
            if item.summary_bullets:
                bullet_text = "\n".join([f"• {b}" for b in item.summary_bullets[:3]])
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": bullet_text
                    }
                })
            
            blocks.append({"type": "divider"})
        
        # Footer
        if briefing.accent_color:
            # Can't use colors in blocks, but mention it's branded
            pass
        
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Sent by {briefing.name} | Powered by Society Speaks"
            }]
        })
        
        # Send to Slack
        payload = {
            "blocks": blocks,
            "unfurl_links": False,
            "unfurl_media": False
        }
        
        # Add channel override if specified
        if briefing.slack_channel_name:
            payload["channel"] = briefing.slack_channel_name
        
        response = requests.post(
            briefing.slack_webhook_url,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully sent brief run {brief_run.id} to Slack for briefing {briefing.id}")
            return True
        else:
            logger.error(f"Slack webhook returned {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending to Slack for briefing {briefing.id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending to Slack: {e}", exc_info=True)
        return False


def test_slack_webhook(webhook_url, test_message=None):
    """
    Test a Slack webhook URL with a simple message.
    
    Args:
        webhook_url: The Slack incoming webhook URL
        test_message: Optional custom test message
        
    Returns:
        tuple: (success: bool, message: str)
    """
    if not webhook_url:
        return False, "No webhook URL provided"
    
    if not webhook_url.startswith("https://hooks.slack.com/"):
        return False, "Invalid Slack webhook URL format"
    
    try:
        payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": test_message or ":white_check_mark: *Slack integration test successful!*\nYour briefings will be delivered to this channel."
                    }
                }
            ]
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, "Webhook test successful! Check your Slack channel."
        else:
            return False, f"Webhook returned status {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "Request timed out. Check your webhook URL."
    except requests.exceptions.RequestException as e:
        return False, f"Request failed: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"
