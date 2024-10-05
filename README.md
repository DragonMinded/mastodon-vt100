# mastodon-vt100

A Mastodon client that uses a VT-100 or compatible terminal to display. Assuming you have a VT-100 compatible terminal connected to your computer through a serial port, you can use this to interact with your home instance much the same way you would the web frontend or a mobile client.

## What to Expect

Right now this is a fairly rudimentary client. The following features are present:

- Basic login/logout flow for your Mastodon-compatible instance.
- Home, local and public timelines, including rendering alt-text and CW text display toggling.
- Saved bookmark list, with all the features of any other timeline.
- Infinite scroll, where additional posts are fetched when you hit the bottom of a timeline.
- Composer box, supporting the ability to post or reply with an optional CW and choosing the visibility.
- Individual post/thread view, supporting the ability to edit/delete your own posts, and ability to interact with other posts such as replying, liking, boosting or bookmarking.
- Preference respecting for CW auto-expansion and composer default post visibility.

What doesn't work that I would like to get to at some point:

- User profile view with profile, pinned posts and user timeline display.
- Conversation/private messaging support.
- Additional formatting support for the post renderer.
- Asynchronous notifications using the terminal bell, notification viewer.

What I may get to at some point in the future:

- Ability to open hyperlinks in posts in focus view by proxying through elinks browser.
- Settings editor for your instance-wide settings.
- Muted/blocked words support in timeline and post views.
- Support for clicking on links to other instances in fake quote boosts.

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
python3 mastodon-vt100 <your home instance here>
```

You can also run with `--help`, like the following example, to see all options:

```
python3 mastodon-vt100 --help
```
