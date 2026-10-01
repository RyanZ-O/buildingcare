"""Usable, deterministic resident guidance with no pretend LLM diagnosis."""
import re


def respond(message, report, building):
    zh = bool(re.search(r'[\u4e00-\u9fff]', message))
    issue = (report or {}).get('issue')
    simulation = (report or {}).get('simulation')
    text = message.casefold()
    urgent = any(w in text for w in ('smoke', 'sparks', 'burning smell', 'gas smell', '烟', '火花', '焦味', '燃气', 'electric shock', '触电'))
    if urgent:
        answer = ('请远离有烟、火花或异味的区域，提醒附近人员并联系楼宇紧急服务；有即时危险时联系当地紧急服务。不要拆设备、触碰电线或反复合闸。' if zh else
                  'Move away from smoke, sparks or unusual burning/gas smells, alert nearby people and contact building emergency services; use local emergency services for immediate danger. Do not open equipment, touch wiring or repeatedly reset breakers.')
    elif any(w in text for w in ('leak', 'water', '漏水', '滴水', '积水')):
        answer = ('暂时远离积水和附近电器，保持通道畅通。安全时拍照并记录漏水的位置和时间；不要拆管道或操作不熟悉的阀门。请把房间和具体位置提交给维护团队。' if zh else
                  'Keep clear of pooled water and nearby electrical devices, and keep access paths open. If safe, photograph the location and note when the leak started. Do not dismantle pipes or operate unfamiliar valves. Report the room and exact location to maintenance.')
    elif any(w in text for w in ('power', 'electric', 'light', '停电', '电', '灯')):
        answer = ('记录哪些灯或设备受影响，以及是否只有这个房间。不要打开配电箱或反复重置断路器；使用安全的备用照明并联系维护团队。此页面不能确认电气故障根因。' if zh else
                  'Note which lights or devices are affected and whether the issue is limited to your room. Use safe backup lighting and contact maintenance. Do not open distribution boards or repeatedly reset breakers. This page cannot confirm an electrical root cause.')
    else:
        answer = ('先检查出风口是否被家具或物品挡住，并只使用您熟悉的房间控制器。记录房间、发生时间、异常声音和是否完全无风；感到明显不适时移到更舒适的区域并联系维护团队。不要拆开风机、风管或电气部件。' if zh else
                  'Check whether furniture or belongings block the vent, and use only familiar room controls. Note the room, start time, unusual sounds and whether airflow is completely absent. Move to a more comfortable space if you feel unwell and contact maintenance. Do not open fans, ducts or electrical equipment.')
    sources = []
    if issue:
        room = next(e for e in building['entities'] if e['id'] == issue['roomId'])
        status = {'submitted': '已提交', 'in_progress': '处理中', 'resolved': '已标记完成'}[issue['status']]
        answer += (f"\n\n您的工单：{issue['title']}；房间：{room['name']}；状态：{status}。" if zh else
                   f"\n\nYour report: {issue['title']}. Room: {room['name']}. Status: {issue['status'].replace('_', ' ')}.")
        sources.append({'id': issue['id'], 'text': issue['title'], 'source': 'This resident report only'})
    if simulation:
        notice = next((n for n in simulation.get('occupantNotices', []) if n['roomId'] == issue['roomId']), None)
        if notice:
            answer += '\n\n' + ('维护方案草稿（未发布，时间未承诺）：' + notice['zh'] if zh else 'Maintenance planning draft (not published; timing not committed): ' + notice['en'])
            sources.append({'id': simulation['id'], 'text': 'Latest scenario for this report', 'source': 'Planning assumptions; not a confirmed outage notice'})
    return {'answer': answer, 'mode': 'resident-guidance-rules', 'sources': sources,
            'note': '预设住户指导演示；没有调用 LLM，也不确认诊断。' if zh else 'Resident guidance demo using preset rules; no LLM call and no diagnosis.'}
