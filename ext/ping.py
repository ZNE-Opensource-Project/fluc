from requests import Session
from time import sleep

HOST = 'node69.lunes.host:3020'
MAX_NODES = 10
BASE = 'https://check-host.net/{}'
CROSSMARK = '<:crossmark:1475897574035685576>'
CHECKMARK = '<:checkmark:1475897532331855893>'
REPORT_WEBHOOK = 'https://discord.com/api/webhooks/1475461449919762515/COjb_F_5lnW9WyFAv6RL5iFIE4F7uFKF0o_2h15sSynGT_TU0kvx95HDOCxpwQDQ5jsi'
webhook_session = Session()

def check():
    session = Session()
    session.headers.update({
        'accept': 'application/json'
    })
    response = session.get(
        BASE.format('check-ping'),
        params={
            'host': HOST,
            'max_nodes': MAX_NODES
        }
    )
    json = response.json()
    request_id = json.get('request_id')
    lines = []
    fails = 0
    if not request_id:
        return None, True
    
    while True:
        response = session.get(BASE.format(f'check-result/{request_id}'))
        result = response.json()
        if all(value is not None for value in result.values()):
            break
        sleep(1)

    for node, values in result.items():
        country = json['nodes'][node][1]
        city = json['nodes'][node][2]
        if not values or not values[0]:
            lines.append(f'{CROSSMARK} {country} ({city}) - TIMEOUT')
            fails += 1
            continue
        ok_rtts = [
            item[1] * 1000
            for item in values[0]
            if item[0] == 'OK'
        ]
        if not ok_rtts:
            lines.append(f'{CROSSMARK} {country} ({city}) - FAIL')
            fails += 1
            continue
        average = round(sum(ok_rtts) / len(ok_rtts), 2)
        lines.append(f'{CHECKMARK} {country} ({city}) - OK ({average}ms)')
    session.close()
    del session
    return lines, fails

def report(lines: list[str], fails: int):
    description = '\n'.join(lines)
    if fails == 9:
        description = f'Not operational in all region\n' + description
        color = 0xff0000
    elif fails:
        description = f'Not operational in {fails} region{'s' if fails > 1 else ''}\n' + description
        color = 0xffff00
    else:
        description = f'Operational in all regions\n' + description
        color = 0x00ff00
    
    embed = {
        'title': 'Status report',
        'description': description,
        'color': color
    }
    _mention = bool(0 if fails < 9 else fails) or None
    message = {
        'content': _mention and '<@&1476229172274790474>',
        'embeds': [embed]
    }
    webhook_session.post(REPORT_WEBHOOK, json=message)

while True:
    try:
        lines, failed = check()
        if lines:
            report(lines, failed)
    except Exception:
        pass
    sleep(60)