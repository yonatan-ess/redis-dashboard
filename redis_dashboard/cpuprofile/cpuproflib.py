import redis


def get_monitor_data(conn, amount=500):
    commands = int(amount)
    command_list = []
    with conn.monitor() as m:
        for command in m.listen():
            commands -= 1
            if commands == 0:
                break
            command_list.append(command)
    return command_list


def re_format_data(command_list):
    # {'time': 1703031048.254477, 'db': 0, 'client_address': '127.0.0.1', 'client_port': '58865', 'client_type': 'tcp', 'command': 'SET key:__rand_int__ VXK'}
    # transfer to
    # {'duration': 0.00254477, 'command': 'SET' , 'key': 'key:__rand_int__', 'value': 'VXK'}
    reformated = []
    for i, command in enumerate(command_list):
        if i > 1:
            command_split = command['command'].split(' ')
            command_type = command_split[0]
            key = command_split[1] if len(command_split) > 1 else None
            value = command_split[2] if len(command_split) > 2 else None
            duration = float(command['time']) - \
                float(command_list[i-1]['time'])
            reformated.append(
                {
                    'duration': duration * 1000,
                    'command': command_type,
                    'keyname': key,
                    'val': value
                })
    return reformated


def sort_commands(commands):
    # sort by duration, and float
    sorted_data = sorted(commands, key=lambda x: x['duration'])
    return sorted_data


def find_top_slowest_command_type(commands):
    # find slowest command type
    # {command: SET, total_duration: 0.00254477}
    slowest_commands = {}
    slowest_command_type = None
    slowest_command_duration = 0
    for command in commands:
        if command['command'] != slowest_command_type:
            if command['duration'] > slowest_command_duration:
                slowest_command_type = command['command']
                slowest_command_duration = command['duration']
                if slowest_command_type not in slowest_commands:
                    slowest_commands[slowest_command_type] = slowest_command_duration
                    slowest_command_duration = 0
                    slowest_command_type = None
                else:
                    slowest_commands[slowest_command_type] = slowest_command_duration + \
                        slowest_commands[slowest_command_type]
                    slowest_command_duration = 0
                    slowest_command_type = None
    return slowest_commands


def command_break_down_by_type(commands):
    command_break_down = {}
    for command in commands:
        if command['command'] not in command_break_down:
            command_break_down[command['command']] = 1
        else:
            command_break_down[command['command']] += 1
    return command_break_down


def key_name_break_down(commands):
    key_break_down = {}
    for command in commands:
        if command['keyname'] not in key_break_down:
            key_break_down[command['keyname']] = 1
        else:
            key_break_down[command['keyname']] += 1
    return key_break_down


def key_name_prefix_break_down(commands):
    key_break_down = {}
    for command in commands:
        if command['keyname'] == None:  # dont include commands with not key such as ping
            continue
        if ":" in command['keyname']:  # ignore none prefix keys
            prefix = command['keyname'].split(':')[0]
            if prefix not in key_break_down:
                key_break_down[prefix] = 1
            else:
                key_break_down[prefix] += 1
        else:
            continue

    return key_break_down


def top_n_slowest_commands(commands, n):
    sorted_commands = sort_commands(commands)
    top_n_commands = sorted_commands[:n]
    return top_n_commands


def get_percentiles_commands_duration(commands):
    sorted_commands = sort_commands(commands)
    percentiles = [0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    percentile_commands = {}
    for percentile in percentiles:
        percentile_commands[percentile] = sorted_commands[int(
            len(sorted_commands) * percentile)]['duration']
    return percentile_commands


def get_total_commands_processed(commands):
    return len(commands)


def get_total_commands_duration(commands):
    total_duration = 0
    for command in commands:
        total_duration += command['duration']
    return total_duration


def count_amount_of_total_commands_per_second(commands):
    # TODO, verify this
    total_commands_per_second = 0
    for command in commands:
        total_commands_per_second += 1/command['duration']
    return total_commands_per_second


def connection(redis_host="localhost", db=0, port=6379, password=None, username=None):
    r = redis.Redis(host=redis_host,
                    port=port,
                    db=db,
                    username=username,
                    password=password,
                    )
    return r


def merge_results(conn, amount):
    commands = get_monitor_data(conn, amount)
    commands_reformat = re_format_data(commands)
    sorted_commands = sort_commands(commands_reformat)
    breakUpCommandByType = command_break_down_by_type(sorted_commands)
    TopSlowestCommands = find_top_slowest_command_type(sorted_commands)
    keyNameBreakDown = key_name_break_down(sorted_commands)
    keyNamePrefixBreakDown = key_name_prefix_break_down(sorted_commands)
    percentilesCommandsDuration = get_percentiles_commands_duration(
        sorted_commands)
    top10SlowestCommands = sorted_commands[-10:]
    getTotalCommandsProcessed = get_total_commands_processed(
        sorted_commands)
    getTotalCommandDuration = get_total_commands_duration(sorted_commands)

    return {
        'TopSlowestCommands': TopSlowestCommands,
        'keyNameBreakDown': keyNameBreakDown,
        'keyNamePrefixBreakDown': keyNamePrefixBreakDown,
        'percentilesCommandsDuration': percentilesCommandsDuration,
        'breakUpCommandByType': breakUpCommandByType,
        'top10SlowestCommands': top10SlowestCommands,
        'getTotalCommandsProcessed': getTotalCommandsProcessed,
        'getTotalCommandDuration': getTotalCommandDuration,
    }
