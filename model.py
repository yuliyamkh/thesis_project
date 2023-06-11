# Model design
import copy
import random
import agentpy as ap
import numpy as np
import networkx as nx
from utils import batch_simulate
from utils import build_tree
import subprocess


class Agent(ap.Agent):

    def setup(self) -> None:
        """
        Set up an agent's initial states.
        This method is called by the model during the setup phase,
        before the simulation starts
        """

        # Initial distribution of A and B
        self.memory = np.random.choice(self.p.lingueme,
                                       size=self.p.memory_size,
                                       p=[self.p.initial_frequency, 1-self.p.initial_frequency])

        # Probability of choosing the innovative variant A
        self.x = self.p.initial_frequency

        # Updated probability of choosing the innovative variant A
        self.updated_x = copy.deepcopy(self.x)

        # Frequency of A
        self.A = np.count_nonzero(self.memory == 'A') / len(self.memory)

        # The produced token
        self.sampled_token = None

    def speak(self) -> None:
        """
        Produce an utterance by sampling one token from the memory
        based on the usage frequency x
        """

        self.sampled_token = np.random.choice(self.p.lingueme,
                                              size=1,
                                              p=[self.updated_x, 1 - self.updated_x])[0]

    def reinforce(self) -> None:
        """
        Reinforce the own behaviour replacing a randomly
        removed token in the memory with the sampled
        token's copy
        """

        # Choose a random index to remove
        random_index = np.random.randint(len(self.memory))

        # Remove the element at the random index
        self.memory = np.delete(self.memory, random_index)

        # Append the sampled token
        self.memory = np.append(self.memory, self.sampled_token)

    def listen(self, neighbour) -> None:
        """
        Listen to the neighbour to match more closely his behaviour
        Replacing the randomly removed token in the memory with the
        neighbour's sampled token
        :param neighbour: one of the k agent's neighbours
        """

        if self.p.neutral_change:
            # Choose a random index to remove
            random_index = np.random.randint(len(self.memory))
            # Remove the element at the random index
            self.memory = np.delete(self.memory, random_index)
            # Append the neighbour's sampled token
            self.memory = np.append(self.memory, neighbour.sampled_token)

        if self.p.replicator_selection and self.p.interactor_selection:
            if self.id > self.p.n:
                if neighbour.id <= self.p.n:
                    if self.sampled_token == 'B' and neighbour.sampled_token == 'A':
                        if random.random() < self.p.selection_pressure:
                            # Choose a random index to remove
                            random_index = np.random.randint(len(self.memory))
                            # Remove the element at the random index
                            self.memory = np.delete(self.memory, random_index)
                            # Append the neighbour's sampled token
                            self.memory = np.append(self.memory, neighbour.sampled_token)
        else:
            if self.p.interactor_selection:
                if self.id > self.p.n:
                    if neighbour.id <= self.p.n:
                        # Choose a random index to remove
                        random_index = np.random.randint(len(self.memory))
                        # Remove the element at the random index
                        self.memory = np.delete(self.memory, random_index)
                        # Append the neighbour's sampled token
                        self.memory = np.append(self.memory, neighbour.sampled_token)

            if self.p.replicator_selection:
                if self.sampled_token == 'B' and neighbour.sampled_token == 'A':
                    if random.random() < self.p.selection_pressure:
                        # Choose a random index to remove
                        random_index = np.random.randint(len(self.memory))
                        # Remove the element at the random index
                        self.memory = np.delete(self.memory, random_index)
                        # Append the neighbour's sampled token
                        self.memory = np.append(self.memory, neighbour.sampled_token)

    def update(self):
        """
        Record belief of choosing the innovative variant v1
        based on the updated memory
        """
        self.A = np.count_nonzero(self.memory == 'A') / len(self.memory)
        self.updated_x = np.count_nonzero(self.memory == 'A') / len(self.memory)


class LangChangeModel(ap.Model):

    def setup(self) -> None:
        """
        Initialize a population of agents and
        the network in which they exist and interact
        """

        self.partition_hierarchy = {}
        self.record_data = True
        self.iteration = 0

        graph = nx.watts_strogatz_graph(
            self.p.agents,
            self.p.number_of_neighbors,
            self.p.network_density
        )

        # Create agents and network
        # Mechanism: neutral change
        self.agents = ap.AgentList(self, self.p.agents, Agent)
        self.network = self.agents.network = ap.Network(self, graph)
        self.network.add_agents(self.agents, self.network.nodes)

        # Initialize the list of networks with the initial network
        self.networks = [self.network]

        # Change setup of agents
        # Mechanism: interactor selection
        if self.p.interactor_selection:
            for agent in self.agents:
                if agent.id <= self.p.n:
                    agent.x = 1
                    agent.memory = np.random.choice(self.p.lingueme,
                                                    size=self.p.memory_size,
                                                    p=[agent.x, 1-agent.x])
                if agent.id > self.p.n:
                    agent.x = 0
                    agent.memory = np.random.choice(self.p.lingueme,
                                                    size=self.p.memory_size,
                                                    p=[agent.x, 1-agent.x])

    def partition_network(self, network):

        # Apply the Kernighan-Lin algorithm to the network
        partition = nx.community.kernighan_lin_bisection(network.graph)

        # Create new subnetworks for the partitioned communities
        subnetworks = [ap.Network(self, network.graph.subgraph(nodes)) for nodes in partition]

        # Update the partition hierarchy
        self.partition_hierarchy[network.id] = [subnetwork.id for subnetwork in subnetworks]

        # Add agents to the subnetworks
        for subnetwork in subnetworks:
            subnetwork.add_agents(self.agents, subnetwork.nodes)

        return subnetworks

    def action(self, agent, neighbor) -> None:
        """
        Definition of actions performed by agent and
        its neighbor during one interaction
        :param agent: agent
        :param neighbor: neighbour
        :return: None
        """

        agent.speak()
        neighbor.speak()

        agent.reinforce()
        neighbor.reinforce()

        agent.listen(neighbor)
        neighbor.listen(agent)

        agent.update()
        neighbor.update()

    def run_interactions(self, network):
        """
        Run interactions between agents and their neighbours.
        Choose two agents who are in a neighborhood
        to each other to interact and perform the actions
        of speaking, reinforcing, and listening
        :return: None
        """

        for t in range(self.p.time):
            # Choose a random agent from agents
            agent = self.random.choice(network.agents.to_list())

            # Initialize neighbors
            neighbors = [j for j in network.neighbors(agent)]

            # Select one random neighbor
            neighbor = self.random.choice(neighbors)

            # Perform action
            self.action(agent=agent, neighbor=neighbor)

    def update(self):
        """
        Record variables after setup and each step
        """

        if self.record_data:
            for network in self.networks:
                # Record average probability x after each simulation step
                # average_updated_x = sum(agent.updated_x for agent in network.agents) / len(network.agents)

                # Record frequency of A
                freq_a = sum(agent.A for agent in network.agents) / len(network.agents)

                # Record the data using self.record()
                self.record(network.id, freq_a)

    def step(self):
        """
        Run interactions according to desired mechanism:
        neutral change, interactor or replicator selection
        """

        # Define interactions between agents within each network
        for network in self.networks:
            self.run_interactions(network)

        self.iteration += 1

        # Check if the desired number of interactions has occurred
        if self.iteration == 10:
            self.iteration = 0
            # Partition the networks and update the list of networks
            new_networks = []
            for network in self.networks:
                new_networks.extend(self.partition_network(network))
            self.networks = new_networks

        # Check if the smallest network has reached 10 nodes
        if min([len(subnet.agents) for subnet in self.networks]) <= 10:
            self.record_data = False
            self.stop()

    def end(self):
        """
        Record evaluation measures at the end of the simulation.
        """
        final_average_updated_x = sum(self.agents.updated_x) / len(self.agents.updated_x)
        self.report('final_x', final_average_updated_x)
        self.report('partition_hierarchy', self.partition_hierarchy)


# Set up parameters for the model
parameters = {'agents': 100,
              'lingueme': ('A', 'B'),
              'memory_size': 10,
              'initial_frequency': 0.3,
              'number_of_neighbors': 8,
              'network_density': 0.01,
              'interactor_selection': False,
              'replicator_selection': False,
              'neutral_change': True,
              'selection_pressure': 0.1,
              'n': 50,
              'time': 100,
              'steps': 1000
              }

model = LangChangeModel(parameters)
results = model.run()

model_results = results.variables.LangChangeModel
column_names = model_results.columns.tolist()
for column_name in column_names:
    print(f'Population: {column_name}\n',
          model_results[column_name].dropna(),
          "\n\n")

# Visualize tree of different populations
partition_hierarchy = results.reporters["partition_hierarchy"].to_dict()[0]
tree = build_tree(partition_hierarchy)
tree.show()
# tree.to_graphviz('populations.dot')
# subprocess.call(["dot", "-Tpng", "populations.dot", "-o", "populations.png"])
exit()

batch_simulate(num_sim=1, model=LangChangeModel, params=parameters)
exit()

sample = ap.Sample(parameters=parameters, n=40)
exp = ap.Experiment(LangChangeModel, sample=sample, iterations=5, record=True)
exp_results = exp.run(n_jobs=-1, verbose=10)
exp_results.save()
exit()
