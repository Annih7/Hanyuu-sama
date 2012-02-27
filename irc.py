from threading import Thread
import logging
import config
import re
import irclib

# Handler constants
# Channels
ALL_CHANNELS = 0
MAIN_CHANNELS = ["#r/a/dio"]
# Nicks
ALL_NICKS = 0 # All nicknames can trigger this
ACCESS_NICKS = 1 # Nicks with halfop or higher can trigger this
OP_NICKS = 2 # Only operators or higher can trigger this
HALFOP_NICKS = 3 # Only half operators can trigger this
VOICE_NICKS = 4 # Only voiced people can trigger this
REGULAR_NICKS = 5 # Only regulars can trigger this
DEV_NICKS = 6 # Only the nicknames defined in config.irc_devs can trigger this

def start():
    global session
    session = Session()
    return session

def shutdown():
    session.close()

class Session(object):
    def __init__(self):
        logging.info("Creating IRC Session")
        self.ready = False
        self.commands = None
        self._handlers = []
        self.exposed = {}
        self.irc = irclib.IRC()
        self.load_handlers()
        self.irc.add_global_handler("all_events", self._dispatcher)
        
        # initialize our process thread
        self.processor_thread = Thread(target=self.processor)
        self.processor_thread.daemon = 1
        self.processor_thread.start()
    def processor(self):
        # Our shiny thread that processes the socket
        while (self._active):
            # Call the process once
            self.irc.process_once(timeout=1)
    def connect(self):
        # We really only need one server
        if (self._active):
            self.server = self.irc.server()
            self.server.connect(config.irc_server,
                                config.irc_port,
                                config.irc_name)
        else:
            raise AssertionError("Can't connect closed Session")
    def close(self):
        self._active = False
        self.irc.disconnect_all("Leaving...")
    def load_handlers(self, load=False):
        # load was ment to be reload, but that fucks up the reload command
        if (load) and (self.commands != None):
            try:
                commands = reload(self.commands)
            except (ImportError):
                # Report this to caller
                raise
        else:
            commands = __import__("hanyuu_commands")
        from types import FunctionType
        for name in dir(commands):
            func = getattr(commands, name)
            if (type(func) == FunctionType):
                try:
                    handler = getattr(func, "handler")
                except (AttributeError):
                    # no handler
                    pass
                else:
                    event, regex, nicks, channels = handler
                    cregex = re.compile(regex)
                    # tuple is:
                    # (Compiled regex, function, event type, allowed nicks,
                    # allowed channels, plain-text regex)
                    self._handlers.append(
                                          (
                                           cregex,
                                           func,
                                           event,
                                           nicks,
                                           channels,
                                           regex
                                           )
                                          )
                try:
                    expose = getattr(func, "exposed")
                except (AttributeError):
                    pass
                else:
                    if (expose == True):
                        # Expose our method please
                        if (hasattr(self, name)):
                            logging.debug("We can't assign you to something that already exists")
                        else:
                            setattr(self, name, func)
                            self.exposed[name] = func
    def reload_handlers(self):
        self._handlers = []
        self.load_handlers(load=True)
    def set_topic(self, channel, topic):
        self.server.topic(channel, topic)
    def wait(self, timeout=None):
        if (self.ready):
            return
        else:
            from time import sleep
            if (timeout == None):
                while True:
                    if (self.ready):
                        break
                    sleep(0.2)
            else:
                for i in xrange(timeout*5):
                    if (self.ready):
                        break
                    sleep(0.2)
            return
    def _dispatcher(self, server, event):
        etype = event.eventtype()
        try:
            if ('!' in event.source()):
                nick = irclib.nm_to_n(event.source())
                userhost = irclib.nm_to_uh(event.source())
                host = irclib.nm_to_h(event.source())
        except (TypeError):
            #Source is None
            pass
        channel = event.target()
        if (etype == 'ctcp'):
            request = event.arguments()[0]
            if (request == 'VERSION'):
                if (hasattr(config, "irc_version")):
                    if (isinstance(config.irc_version, basestring)):
                        server.ctcp_reply(nick, 'VERSION {version}'\
                                  .format(version=config.irc_version))
                    else:
                        logging.info("IRC Version configuration incorrect")
                else:
                    server.ctcp_reply(nick, 'VERSION irclib 4.8')
        elif (etype == 'invite'):
            server.join(event.arguments()[0])
        elif (etype == 'disconnect'):
            # We disconnected ;_;
            self.ready = False
        elif (etype == 'endofmotd'):
            if (hasattr(config, "irc_pass")):
                if (isinstance(config.irc_pass, basestring)):
                    server.privmsg('nickserv', 'identify {pwd}'\
                           .format(pwd=config.irc_pass))
                else:
                    logging.info("IRC Password configuration incorrect")
            if (hasattr(config, "irc_channels")):
                try:
                    channels = ", ".join(config.irc_channels)
                except (TypeError):
                    logging.info("IRC Channel configuration incorrect")
                else:
                    server.join(channels)
            self.ready = True
        elif (etype == "pubmsg"):
            # TEXT OH SO MUCH TEXT
            text = event.arguments()[0]
            for handler in [handlers for handlers in self._handlers if \
                            handlers[2] == "on_text"]:
                if (handler[0].match(text)):
                    # matchy
                    nicks, chans = handler[3:5]
                    if (not nicks == ALL_NICKS):
                        if (type(nicks) == list):
                            # normal list man
                            if (not nick in nicks):
                                continue
                        elif (type(nicks) == int):
                            # constant
                            # TODO:
                            # We can make this all a dictionary most likely at
                            # the top of the module
                            if (nicks in [ACCESS_NICKS,
                                          OP_NICKS,
                                          HALFOP_NICKS,
                                          VOICE_NICKS,
                                          REGULAR_NICKS]):
                                if (not {
                                        ACCESS_NICKS: server.hasaccess,
                                        OP_NICKS: server.isop,
                                        HALFOP_NICKS: server.ishop,
                                        VOICE_NICKS: server.isvoice,
                                        REGULAR_NICKS: server.isnormal,
                                        }[nicks](channel, nick)):
                                    continue
                            elif (nicks == DEV_NICKS):
                                if (not nick in config.irc_devs):
                                    continue
                        else:
                            # We don't even know just ignore it
                            # Send to debugging for cleanness
                            logging\
                        .debug("HandlerError: {type} on 'nick' not accepted"\
                                          .format(type=str(type(nicks))))
                            continue
                    if (not chans == ALL_CHANNELS):
                        # Do channel filtering
                        if (type(chans) == list):
                            # normal list
                            if (not channel in chans):
                                continue
                        elif (type(chans) == int):
                            # constant (WE DON'T HAVE ANY RIGHT NOW)
                            continue
                        else:
                            # We don't even know just ignore it
                            # Send to debugging for cleanness
                            logging\
                        .debug("HandlerError: {type} on 'channel' not accepted"\
                                          .format(type=str(type(chans))))
                            continue
                    # Call our func here since the above filters will call
                    # 'continue' if the filter fails
                    handler[1](server, nick, channel, text, userhost)