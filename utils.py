from collections import defaultdict, namedtuple
from datetime import datetime
from operator import attrgetter

from dateutil.parser import parse
from jira import JIRA
from pandas import DataFrame, read_csv, DateOffset, bdate_range
from tqdm import tqdm_notebook

Transition = namedtuple('Transition', ['created', 'from_str', 'to_str'])


def connect(host, username, password):
    return JIRA(host, basic_auth=(username, password))


def iter_issues(client, jql, start_at=0, expand=None):
    """search_issues doesn't iterate despite what the JIRA docs say."""
    while True:
        issues = client.search_issues(jql, startAt=start_at, expand=expand)

        yield from issues
        start_at += len(issues)
        if start_at >= issues.total:
            break


def total_issues(client, jql):
    return client.search_issues(jql).total


def load_data(jira_client, jql, path='data.csv', refresh=True):
    """Loads the JIRA data into a DataFrame, or loads the DataFrame from a CSV."""
    if refresh:
        data = []

        total = total_issues(jira_client, jql)

        for issue in tqdm_notebook(iter_issues(jira_client, jql, expand='changelog'), total=total):
            d1 = {'key': issue.key, 'story_points': story_point(issue)}
            d2 = time_in_states(issue)
            data.append({**d1, **d2})

        df = DataFrame(data)
        df.to_csv(path)
    else:
        df = read_csv(path)

    return df


def history(issue, field):
    """Yields the history items which match the given fieldId"""
    for h in issue.changelog.histories:
        for item in h.items:
            if getattr(item, 'fieldId', None) == field:
                yield Transition(created=parse(h.created), from_str=item.fromString, to_str=item.toString)


def story_points(issue):
    yield from history(issue, 'customfield_10203')


def transitions(issue):
    yield from history(issue, 'status')


def story_point(issue):
    """
    Returns the 'story points' assigned to an issue. Finds the max value ever assigned
    because we used to decrease the assigned story points. Also deals with garbage story point
    values (by ignoring them ;).
    """
    max_story_point = 1
    for update in sorted(story_points(issue), key=attrgetter('created')):
        try:
            max_story_point = max(max_story_point, float(update.to_str))
        except:
            pass

    return max_story_point


def business_hours(start, end):
    """Computes the number of working hours between two dates. (There's gotta be a better way to do this.)"""
    return len(bdate_range(start, end, freq=DateOffset(hours=1)))


def time_in_states(issue):
    """Returns a dictionary states mapped to the business hours the issue stayed the state."""
    durations = defaultdict(int)
    previous = None

    # Sort the transitions by created date
    for transition in sorted(transitions(issue), key=attrgetter('created')):
        start = previous.created if previous else parse(issue.fields.created)
        end = transition.created.astimezone(start.tzinfo)

        # Deals with transitions back to 'earlier' states
        durations[transition.from_str] += business_hours(start, end)

        previous = transition

    # Don't forget the 'current' state
    start = previous.created
    end = datetime.now(previous.created.tzinfo)
    durations[previous.to_str] = business_hours(start, end)

    return durations
