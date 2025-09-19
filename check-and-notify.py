import requests
import logging
import os
import sys
import json
from datetime import datetime
from urllib.parse import urlparse

log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
  format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
)
log = logging.getLogger(__name__)

# Default to the oldest ten documents

max_docs = os.getenv('MAX_DOCS', 10)
try:
  log.info(f'Max docs to be returned: {int(max_docs)}')
except Exception:
  log.error(f'max_docs ({max_docs}) needs to be an integer (or 0) - cannot continue')
  sys.exit(1)

page_list_filename = os.getenv('PAGE_LIST_FILENAME', 'page-list.json')
slack_webhook_url = os.getenv('SLACK_WEBHOOK_URL', '')
slack_template_filename = 'templates/slack_message.json'


def get_doc_list(url):
  try:
    response = requests.get(url, timeout=10)
  except Exception as e:
    log.warning(f'Failed to fetch {url}: {e}')
    return None

  if response.status_code == 200:
    try:
      data = response.json()
      if data:
        return data
      else:
        log.warning(f'Empty JSON data from {url}')
        return None
    except json.JSONDecodeError as e:
      log.warning(f'Invalid JSON from {url}: {e}')
    return None
  else:
    log.warning(f'Failed to fetch {url}: HTTP {response.status_code}')
    return None


def get_json(filename):
  try:
    with open(filename, 'r') as f:
      data = json.load(f)
      return data
  except (FileNotFoundError, json.JSONDecodeError) as e:
    log.warning(f'Could not load or parse {filename}: {e}')
    return []


def get_out_of_date_docs(doc_list):
  # get the most out-of-date documents and build a list to send to slack
  out_of_date_docs = []
  for doc in doc_list:
    title = doc.get('title')
    url = doc.get('url')
    review_again_str = doc.get('reviewAgain')
    if review_again_str and url:
      try:
        review_again_date = datetime.strptime(review_again_str, '%Y-%m-%d')
        days_overdue = (datetime.now() - review_again_date).days
        if days_overdue > 0:
          out_of_date_docs.append(
            {'title': title, 'url': url, 'days_overdue': days_overdue}
          )
      except Exception as e:
        log.warning(
          f"Could not parse reviewAgain date '{review_again_str}' for {url}: {e}"
        )

  out_of_date_docs.sort(key=lambda x: x['days_overdue'], reverse=True)
  return out_of_date_docs[
    : (int(max_docs) if int(max_docs) > 0 else len(out_of_date_docs))
  ]


def build_slack_message(overdue_docs, pages_url):
  # The slack template needs to have blocks as follows:
  # - the first block contains the message title in a text field,
  # - the second block contains the heading of the list
  # - the penultimate block contains the list of the documents
  # - the last block contains the URL for the github tech docs monitor
  if slack_message_template := get_json(slack_template_filename):
    header_text = f":rocco-docco-quokka: Hello. :paw_prints: This is Rocco, your friendly docco quokka. I've found {len(overdue_docs)} page{('s' if len(overdue_docs) != 1 else '')} overdue for review."
    max_docs_int = int(max_docs)
    list_heading_text = f'Here {("is the full list:" if (max_docs_int == 0 or len(overdue_docs) <= max_docs_int) else f"are the top {max_docs_int} oldest:")}'
    list_text = ''
    for doc in overdue_docs:
      parsed_url = urlparse(pages_url)
      base_url = f'{parsed_url.scheme}://{parsed_url.netloc}/'
      list_text += f'• <{base_url}{doc.get("url")}|{doc.get("title")}> ({doc.get("days_overdue")} day{("s" if int(doc.get("days_overdue")) != 1 else "")} ago)\n'
    try:
      slack_message_template['blocks'][0]['text']['text'] = header_text
      slack_message_template['blocks'][1]['text']['text'] = list_heading_text
      slack_message_template['blocks'][-2]['text']['text'] = list_text
    except Exception as e:
      log.warning(f"Couldn't build Slack message from template - {e}")
      return None
    log.debug(json.dumps(slack_message_template, indent=2))
    return slack_message_template
  else:
    log.warning(f"Couldn't load Slack message template from {slack_template_filename}")
    return None


def slack_notify(slack_message):
  try:
    headers = {'Content-type': 'application/json'}
    response = requests.post(
      slack_webhook_url, headers=headers, data=json.dumps(slack_message)
    )
    success = response.status_code == 200
    if success:
      return True
    else:
      return False
  except Exception as e:
    log.error(f"Couldn't send Slack message: {e}")
    return False


def main():
  page_list = get_json(page_list_filename)
  if isinstance(page_list, dict) and 'pages' in page_list:
    for pages_url in page_list['pages']:
      if doc_list := get_doc_list(pages_url):
        if overdue_docs := get_out_of_date_docs(doc_list):
          log.info(f'overdue documents:\n{json.dumps(overdue_docs, indent=2)}')
          if slack_webhook_url:
            if slack_message := build_slack_message(overdue_docs, pages_url):
              if slack_notify(slack_message):
                log.info('Slack notification sent')
  else:
    log.warning(
      f"{page_list_filename} did not contain expected 'pages' key or is not a dict"
    )


if __name__ == '__main__':
  main()
