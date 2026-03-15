# xDripLooker
Visualizing xDrip+ Data in Looker

## Main Idea
As a type-1 diabetic, I want a site where others (my wife, my doctors, etc.) can view my glucose levels over time. It would also be nice to have my values over time stored in a database where I can analyze the data myself.

I use xDrip+ on my phone to hijack my Dexcom glucometer's Bluetooth signal. The open-source app is just better, IMO, than the Dexcom software. I also have customized a watchface that works well with this setup.

This repo may end up being just documentation.

Just getting this working and then will improve whatever needs improving. While I'd rather use InfluxDB, it would currently be more challenging to run and also to get connected to Looker. I wish there were a PostgreSQL option in xDrip, but there isn't. So, we'll use MongoDB because there are easy (and free) instances, and connecting to Looker is easy.

## Set Up MongoDB

- Visit [cloud.mongodb.com](http://cloud.mongodb.com), set up an account or log in to an existing account.
- My "organization" and "project" seems to have been set up automatically with generic names: `Jason's Org - 2026-03-09` and `Project 0`. You may need to set these up yourself.
- Go into your organization and project, click on "Clusters" in the side menu. Click on "Build a Cluster."
- I'm going to try using the free level cluster. As of writing this, it has a 512 MiB storage limit with shared vCPU and RAM. My cluster is named `Cluster0`. I'm going to preload the sample dataset for testing. I'm running on GCP with the region set to Iowa (us-central1). (The location is important because we will want to use the same region later for Looker so we save on costs.)
- After saving the configuration, I was asked to create a database user and password. I placed those into my password manager and created the user.
- Choose a conenction method. I am using the MongoDB drivers. I will allow xDrip+ to use its existing drivers, but will use Python for testing.

Getting the config into xDrip is a bit tedious. See gemini conversation and clean this up when that works.

Remove the SRV connection string and you get the full old-school Python connection string.

Update the network access. During the setup process, your IP address will be used as the only one capable of conencting to the DB. Document how to change that here.

## Creating a Test Environment

` conda create --name xdrip python=3.1`

and

`conda activate xdrip`

I installed pymongo, jupyter, jupyterlab, and pandas from the conda forge channels.
