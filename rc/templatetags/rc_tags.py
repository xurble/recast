from django import template
import email

register = template.Library()

from rc.models import SubscriptionPost


@register.filter(name="hoursmins")
def hoursmins(value):
    if value == None or value == "":
        return ""

    s = int(value) * 60

    hours, remainder = divmod(s, 3600)
    minutes, seconds = divmod(remainder, 60)

    return "%d:%02d" % (hours, minutes)


@register.filter(name="feed_datetime")
def feed_datetime(value):
    return email.utils.formatdate(float(value.strftime("%s")))


@register.filter(name="subscription_created")
def subscription_created(post):
    if hasattr(post, "__iter__"):
        return post["created_for_subscription"]

    try:
        sp = SubscriptionPost.objects.filter(post=post).filter(
            subscription=post.current_subscription
        )[0]
    except:
        sp = SubscriptionPost(post=post, subscription=post.current_subscription)
        sp.save()

    return email.utils.formatdate(float(sp.created.strftime("%s")))
