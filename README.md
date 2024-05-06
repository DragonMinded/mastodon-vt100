# mastodon-vt100

A Mastodon client that uses a VT-100 or compatible terminal to display. Assuming you have a VT-100 compatible terminal connected to your computer through a serial port, you can use this to interact with your home instance much the same way you would the web frontend or a mobile client.

## What to Expect

Right now this is a fairly rudimentary client. The following features are present:

- Basic login/logout flow for your Mastodon-compatible instance.
- Home timeline, including rendering alt-text and CW text display toggling.
- Infinite scroll, where additional posts are fetched when you hit the bottom of the timeline.
- Composer box, supporting the ability to post with an optional CW and choosing the visibility.

What doesn't work that I would like to get to at some point:

- Preferences respecting in post composer, so it defaults to your default visibility.
- Post focus view, showing ancestors and descendant replies.
- Ability to reply to posts instead of only posting to your own timeline.
- User profile view.
- Ability to like or boost a post from the focus view.
- Support for other timelines, such as local timeline and private messages.
- Additional formatting support for the post renderer.

What I may get to at some point in the future:

- Ability to open hyperlinks in posts in focus view by proxying through elinks browser.
- Post editor for previously-posted posts.
- Settings editor for your instance-wide settings.

## Running This

If you are non-technical, or you just want to try it out without tinkering, I recommend using `pipx` to install the client. For help and instruction on setting up `pipx` on your computer, visit [pipx's installation page](https://pipx.pypa.io/stable/installation/). If you have `pipx` installed already, run the following line to install the mastodon-vt100 client on your computer.

```
pipx install git+https://github.com/DragonMinded/mastodon-vt100
```

Once that completes, you can run this client by typing the following line, substituting your instance:

```
mastodon-vt100 <your home instance here>
```

You can also run with `--help`, like the following example, to see all options:

```
mastodon-vt100 --help
```

Note that original VT-100 terminals, and variants such as the 101 and 102, need the XON/XOFF flow control option enabled. Make sure you enable flow control on the terminal itself, and then use the `--flow` argument to avoid overloading the terminal. Newer terminals such as mid-80s VT-100 clones often do not suffer from this problem and keep up just fine.

Happy posting!

## Development

To get started, first install the requirements using a command similar to:

```
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-dev.txt
```

Then, you can run the application similar to:

```
python3 -m masto <your home instance here>
```

You can also run with `--help`, like the following example, to see all options:

```
python3 -m masto --help
```
