from django import template

register = template.Library()


@register.filter(name='hoursmins')
def hoursmins(value):

    
  
    if value == None or value == "":
        return ""
    
    s = int(value) * 60
    
    hours, remainder = divmod(s, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return "%d:%02d" % (hours,minutes)
    